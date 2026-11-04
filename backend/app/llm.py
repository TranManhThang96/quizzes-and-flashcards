"""Gọi gateway LLM tương thích OpenAI, ép JSON và validate bằng pydantic."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI, BadRequestError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import ValidationError

from app.config import Settings
from app.content import parse_content

# Một hàm nhận messages kiểu OpenAI và trả về dict đã parse. Test dùng hàm giả.
JsonLlm = Callable[[list[ChatCompletionMessageParam]], Awaitable[dict[str, Any]]]

_SYSTEM_PROMPT = """Bạn soạn nội dung học tập từ văn bản nguồn của người dùng.

Chỉ trả về MỘT object JSON, không kèm chữ nào khác, dạng:
{"items": [{"level": "<level>", "content": {...}}]}

Quy tắc:
- Mỗi item có "level" đúng bằng một level được yêu cầu.
- Số item mỗi level không vượt quá số lượng được yêu cầu.
- Nội dung viết bằng cùng ngôn ngữ với văn bản nguồn.
- Chỉ dùng thông tin có trong nguồn; không bịa thêm dữ kiện.
- Với "vocab", "word" và "examples" là tiếng Anh, "meaning" là nghĩa tiếng Việt.
"""

_SCHEMAS: dict[str, str] = {
    "flashcard": (
        'content = {"front": "câu hỏi ngắn", "back": "câu trả lời"}; '
        "front và back không rỗng."
    ),
    "vocab": (
        'content = {"word": "từ tiếng Anh", "part_of_speech": "noun|verb|adj|...", '
        '"meaning": "nghĩa tiếng Việt", "ipa": "/.../", '
        '"examples": ["câu ví dụ tiếng Anh"]}; examples có thể rỗng.'
    ),
    "question": (
        'content = {"type": "mcq" hoặc "true_false", "prompt": "câu hỏi", '
        '"options": ["...", "..."], "answer": "một phần tử của options", '
        '"explanation": "giải thích ngắn"}; true_false có đúng 2 lựa chọn, '
        "mcq có 2 đến 8 lựa chọn khác nhau."
    ),
}

_LEVEL_HINT = (
    "easy: nhớ lại trực tiếp; medium: hiểu và áp dụng một bước; "
    "hard: nhiều bước hoặc so sánh; expert: tổng hợp, biên."
)


class LlmError(RuntimeError):
    """Lỗi gọi gateway hoặc JSON không dùng được, kể cả sau khi đã retry."""


class LlmOutputError(LlmError):
    """JSON đúng cú pháp nhưng sai schema."""


class OpenAiJsonLlm:
    """Bọc `openai.AsyncOpenAI`, ép `response_format=json_object` khi gateway hỗ trợ."""

    def __init__(
        self, settings: Settings, *, client: AsyncOpenAI | None = None
    ) -> None:
        self._model = settings.llm_model
        self._client = client or AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "missing-key",
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )

    async def _request(
        self, messages: list[ChatCompletionMessageParam], *, json_mode: bool
    ) -> Any:
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.2,
            **kwargs,
        )

    async def __call__(
        self, messages: list[ChatCompletionMessageParam]
    ) -> dict[str, Any]:
        try:
            completion = await self._request(messages, json_mode=True)
        except BadRequestError:
            # Some OpenAI-compatible gateways reject `response_format`. The
            # prompt already describes the JSON, so retry once without it.
            try:
                completion = await self._request(messages, json_mode=False)
            except Exception as exc:  # noqa: BLE001
                raise LlmError(f"Gọi LLM thất bại: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - SDK ném nhiều lớp lỗi mạng
            raise LlmError(f"Gọi LLM thất bại: {exc}") from exc
        raw = (completion.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            # Một số gateway vẫn bọc JSON trong code fence dù đã yêu cầu JSON.
            raw = raw.strip("`")
            raw = raw[raw.find("{") :] if "{" in raw else raw
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlmOutputError(f"LLM không trả JSON hợp lệ: {exc}") from exc
        if not isinstance(data, dict):
            raise LlmOutputError("LLM phải trả về một object JSON")
        return data


def build_messages(
    *,
    kind: str,
    topic_name: str,
    chunk: str,
    counts: dict[str, int],
) -> list[ChatCompletionMessageParam]:
    wanted = ", ".join(f"{level}: {count}" for level, count in counts.items())
    instructions = "\n".join(
        [
            f"Chủ đề: {topic_name}",
            f"Loại nội dung: {kind}",
            f"Số lượng cần: {wanted}",
            _LEVEL_HINT,
            f"Schema content: {_SCHEMAS[kind]}",
        ]
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{instructions}\n\nVăn bản nguồn:\n<<<\n{chunk}\n>>>",
        },
    ]


def validate_response(
    kind: str, data: dict[str, Any], counts: dict[str, int]
) -> list[dict[str, Any]]:
    """Kiểm tra đầu ra LLM theo `kind`; bỏ item vượt số lượng, lỗi schema thì raise."""
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise LlmOutputError('JSON phải có trường "items" là một mảng')
    accepted: list[dict[str, Any]] = []
    seen: dict[str, int] = dict.fromkeys(counts, 0)
    errors: list[str] = []
    for index, entry in enumerate(raw_items):
        if not isinstance(entry, dict):
            errors.append(f"items[{index}] phải là object")
            continue
        level = entry.get("level")
        content = entry.get("content")
        if level not in counts:
            errors.append(f"items[{index}].level {level!r} không có trong yêu cầu")
            continue
        if not isinstance(content, dict):
            errors.append(f"items[{index}].content phải là object")
            continue
        try:
            parsed = parse_content(kind, content)
        except ValidationError as exc:
            errors.append(
                f"items[{index}].content sai schema: {exc.errors()[0]['msg']}"
            )
            continue
        if seen[level] >= counts[level]:
            # Vượt số lượng yêu cầu: bỏ qua, không phải lỗi.
            continue
        seen[level] += 1
        accepted.append({"level": level, "content": parsed.model_dump()})
    if errors:
        raise LlmOutputError("; ".join(errors[:5]))
    if not accepted:
        raise LlmOutputError("LLM không trả về item nào dùng được")
    return accepted


async def generate_chunk(
    llm: JsonLlm,
    *,
    kind: str,
    topic_name: str,
    chunk: str,
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Sinh item cho một chunk; sai schema thì retry một lần kèm lỗi cụ thể."""
    messages = build_messages(
        kind=kind, topic_name=topic_name, chunk=chunk, counts=counts
    )
    data = await llm(messages)
    try:
        return validate_response(kind, data, counts)
    except LlmOutputError as exc:
        retry_messages: list[ChatCompletionMessageParam] = [
            *messages,
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    f"Đầu ra trên sai: {exc}. Trả lại đúng object JSON theo schema, "
                    "không thêm chữ nào khác."
                ),
            },
        ]
        second = await llm(retry_messages)
        return validate_response(kind, second, counts)
