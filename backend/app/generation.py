"""Sinh item nháp từ một nguồn: gọi LLM theo chunk rồi ghi vào bảng items."""

from pydantic import BaseModel, Field, model_validator

from app.content import Level


class GenerationError(RuntimeError):
    """Job không chạy được: tham số sai, nguồn/chủ đề biến mất hoặc LLM lỗi."""


class LevelCount(BaseModel):
    level: Level
    count: int = Field(ge=1, le=50)


class JobParams(BaseModel):
    """Tham số job, dùng chung cho API và dịch vụ sinh nội dung."""

    kind: str
    levels: list[LevelCount] = Field(min_length=1)

    @model_validator(mode="after")
    def _levels_are_unique(self) -> "JobParams":
        levels = [entry.level for entry in self.levels]
        if len(set(levels)) != len(levels):
            raise ValueError("levels must not repeat")
        if self.kind not in ("flashcard", "vocab", "question"):
            raise ValueError("kind must be flashcard, vocab or question")
        return self

    @property
    def total(self) -> int:
        return sum(entry.count for entry in self.levels)

    def counts(self) -> dict[str, int]:
        return {entry.level: entry.count for entry in self.levels}
