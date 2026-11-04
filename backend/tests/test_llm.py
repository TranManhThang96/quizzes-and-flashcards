import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import Settings
from app.llm import (
    LlmOutputError,
    OpenAiJsonLlm,
    generate_chunk,
    validate_response,
)
from tests.fake_llm import FakeLlm, batch, flashcard

COUNTS = {"easy": 2}
MESSAGES = [{"role": "user", "content": "x"}]


def test_valid_output_is_validated_by_pydantic_and_kept():
    data = batch(
        flashcard("easy", "Lãi kép là gì?"), flashcard("easy", "Cổ phiếu là gì?")
    )

    items = validate_response("flashcard", data, COUNTS)

    assert [item["content"]["front"] for item in items] == [
        "Lãi kép là gì?",
        "Cổ phiếu là gì?",
    ]


def test_items_beyond_the_requested_count_are_dropped():
    data = batch(*(flashcard("easy", f"câu {index}") for index in range(5)))

    assert len(validate_response("flashcard", data, COUNTS)) == 2


def test_unknown_level_is_an_error():
    with pytest.raises(LlmOutputError):
        validate_response("flashcard", batch(flashcard("expert", "a")), COUNTS)


def test_content_failing_the_schema_is_an_error():
    data = batch({"level": "easy", "content": {"front": "", "back": "x"}})
    with pytest.raises(LlmOutputError) as excinfo:
        validate_response("flashcard", data, COUNTS)
    assert "items[0]" in str(excinfo.value)


def test_a_non_string_level_is_an_output_error_not_a_type_error():
    data = batch({"level": ["easy"], "content": {"front": "a", "back": "b"}})

    with pytest.raises(LlmOutputError):
        validate_response("flashcard", data, COUNTS)


def test_missing_items_key_is_an_error():
    with pytest.raises(LlmOutputError):
        validate_response("flashcard", {"results": []}, COUNTS)


def test_empty_item_list_is_an_error():
    with pytest.raises(LlmOutputError):
        validate_response("flashcard", {"items": []}, COUNTS)


async def test_invalid_output_is_retried_once_with_the_validation_error():
    llm = FakeLlm(
        [
            batch({"level": "easy", "content": {"front": "", "back": "x"}}),
            batch(flashcard("easy", "Lãi kép là gì?")),
        ]
    )

    items = await generate_chunk(
        llm, kind="flashcard", topic_name="Tài chính", chunk="nguồn", counts=COUNTS
    )

    assert len(items) == 1
    assert len(llm.calls) == 2
    retry_message = llm.calls[1][-1]["content"]
    assert "sai" in retry_message


async def test_two_invalid_answers_fail_the_chunk():
    bad = batch({"level": "easy", "content": {"front": "", "back": "x"}})
    llm = FakeLlm([bad, bad])

    with pytest.raises(LlmOutputError):
        await generate_chunk(
            llm, kind="flashcard", topic_name="Tài chính", chunk="nguồn", counts=COUNTS
        )

    assert len(llm.calls) == 2


async def test_a_non_string_level_is_retried_instead_of_raising_type_error():
    llm = FakeLlm(
        [
            batch({"level": ["easy"], "content": {"front": "a", "back": "b"}}),
            batch(flashcard("easy", "Lãi kép là gì?")),
        ]
    )

    items = await generate_chunk(
        llm, kind="flashcard", topic_name="Tài chính", chunk="nguồn", counts=COUNTS
    )

    assert len(items) == 1
    assert len(llm.calls) == 2


async def test_a_non_json_first_reply_is_retried_once():
    llm = FakeLlm(
        [
            LlmOutputError("LLM không trả JSON hợp lệ"),
            batch(flashcard("easy", "Lãi kép là gì?")),
        ]
    )

    items = await generate_chunk(
        llm, kind="flashcard", topic_name="Tài chính", chunk="nguồn", counts=COUNTS
    )

    assert len(items) == 1
    assert len(llm.calls) == 2
    assert "sai" in llm.calls[1][-1]["content"]


async def test_two_non_json_replies_fail_after_one_retry():
    llm = FakeLlm([LlmOutputError("lần một"), LlmOutputError("lần hai")])

    with pytest.raises(LlmOutputError):
        await generate_chunk(
            llm, kind="flashcard", topic_name="Tài chính", chunk="nguồn", counts=COUNTS
        )

    assert len(llm.calls) == 2


def _client_returning(payload: str) -> tuple[AsyncOpenAI, dict[str, object]]:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": payload},
                    }
                ],
            },
        )

    client = AsyncOpenAI(
        base_url="https://gateway.test/v1",
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, seen


async def test_openai_client_forces_json_mode_and_parses_the_reply():
    client, seen = _client_returning('{"items": [{"level": "easy"}]}')

    llm = OpenAiJsonLlm(
        Settings(database_url="postgresql+psycopg://x/y"), client=client
    )
    data = await llm(MESSAGES)

    assert data == {"items": [{"level": "easy"}]}
    assert seen["url"] == "https://gateway.test/v1/chat/completions"
    assert seen["body"]["response_format"] == {"type": "json_object"}


async def test_openai_client_unwraps_a_fenced_json_reply():
    client, _ = _client_returning('```json\n{"items": []}\n```')

    llm = OpenAiJsonLlm(
        Settings(database_url="postgresql+psycopg://x/y"), client=client
    )

    assert await llm(MESSAGES) == {"items": []}


async def test_openai_client_rejects_a_non_json_reply():
    client, _ = _client_returning("xin chào")

    llm = OpenAiJsonLlm(
        Settings(database_url="postgresql+psycopg://x/y"), client=client
    )

    with pytest.raises(LlmOutputError):
        await llm(MESSAGES)


async def test_a_gateway_rejecting_response_format_is_retried_without_it():
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"items": []}'},
                    }
                ],
            },
        )

    client = AsyncOpenAI(
        base_url="https://gateway.test/v1",
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    llm = OpenAiJsonLlm(
        Settings(database_url="postgresql+psycopg://x/y"), client=client
    )

    assert await llm(MESSAGES) == {"items": []}
    assert "response_format" in seen[0]
    assert "response_format" not in seen[1]
