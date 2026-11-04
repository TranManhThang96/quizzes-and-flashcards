"""LLM giả: trả lần lượt các response đã chuẩn bị, ghi lại messages."""

from typing import Any

from openai.types.chat import ChatCompletionMessageParam


class FakeLlm:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatCompletionMessageParam]] = []

    async def __call__(
        self, messages: list[ChatCompletionMessageParam]
    ) -> dict[str, Any]:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("FakeLlm đã hết response")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def flashcard(level: str, front: str, back: str = "nghĩa") -> dict[str, Any]:
    return {"level": level, "content": {"front": front, "back": back}}


def batch(*items: dict[str, Any]) -> dict[str, Any]:
    return {"items": list(items)}
