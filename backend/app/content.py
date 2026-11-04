import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.text import fold

Level = Literal["easy", "medium", "hard", "expert"]
Kind = Literal["flashcard", "vocab", "question"]
ItemStatus = Literal["draft", "published", "archived"]


class FlashcardContent(BaseModel):
    front: str = Field(min_length=1, max_length=2000)
    back: str = Field(min_length=1, max_length=4000)


class VocabContent(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    part_of_speech: str = Field(min_length=1, max_length=40)
    meaning: str = Field(min_length=1, max_length=2000)
    ipa: str = Field(default="", max_length=200)
    examples: list[str] = Field(default_factory=list, max_length=10)


class QuestionContent(BaseModel):
    type: Literal["mcq", "true_false"]
    prompt: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(min_length=2, max_length=8)
    answer: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def _options_are_consistent(self) -> "QuestionContent":
        if self.type == "true_false" and len(self.options) != 2:
            raise ValueError("true_false questions need exactly two options")
        if len(set(self.options)) != len(self.options):
            raise ValueError("options must be unique")
        if self.answer not in self.options:
            raise ValueError("answer must be one of the options")
        return self


Content = FlashcardContent | VocabContent | QuestionContent

_SCHEMAS: dict[str, type[BaseModel]] = {
    "flashcard": FlashcardContent,
    "vocab": VocabContent,
    "question": QuestionContent,
}


def parse_content(kind: str, raw: dict[str, Any]) -> Content:
    """Validate one item's JSONB payload against its kind's schema."""
    return _SCHEMAS[kind].model_validate(raw)  # type: ignore[return-value]


def content_key(kind: str, content: Content) -> str:
    if kind == "flashcard":
        assert isinstance(content, FlashcardContent)
        return fold(content.front)
    if kind == "vocab":
        assert isinstance(content, VocabContent)
        return f"{fold(content.word)}\x1f{fold(content.part_of_speech)}"
    assert isinstance(content, QuestionContent)
    return fold(content.prompt)


def content_hash(kind: str, content: Content) -> str:
    return hashlib.sha256(f"{kind}\n{content_key(kind, content)}".encode()).hexdigest()
