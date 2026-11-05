"""Sinh item nháp từ một nguồn: gọi LLM theo chunk rồi ghi vào bảng items."""

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import chunk_text, plan_chunks
from app.content import Level, content_hash, parse_content
from app.llm import JsonLlm, generate_chunk
from app.models import GenerationJob, Item, Source, Topic

Clock = Callable[[], datetime]


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


async def _insert_draft(
    session: AsyncSession,
    *,
    topic_id: int,
    source_id: int,
    kind: str,
    level: str,
    content: dict[str, object],
) -> bool:
    """Chèn một item draft, bỏ qua nếu nội dung đã có trong chủ đề.

    Trùng được xử lý ở tầng DB (`ON CONFLICT DO NOTHING`) nên hai worker chạy
    song song cũng không tạo bản ghi thứ hai; đây cũng là điều làm job retry
    an toàn. Item `archived` vẫn giữ `content_hash` nên vẫn bị tính là trùng.
    """
    parsed = parse_content(kind, content)
    statement = (
        pg_insert(Item)
        .values(
            topic_id=topic_id,
            level=level,
            kind=kind,
            content=parsed.model_dump(),
            status="draft",
            content_hash=content_hash(kind, parsed),
            source_id=source_id,
        )
        .on_conflict_do_nothing(index_elements=["topic_id", "content_hash"])
        .returning(Item.id)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def run_job(
    session: AsyncSession,
    job: GenerationJob,
    *,
    llm: JsonLlm,
    now: Clock,
    chunk_chars: int = 8000,
) -> dict[str, int]:
    """Chạy một job đã được claim; trả về `{"created": n, "skipped": m}`.

    Mỗi chunk commit riêng và cập nhật `result` nên job bị thu hồi giữa đường
    vẫn giữ được tiến độ; lần chạy sau sinh lại từ đầu nhưng mọi item đã có
    (kể cả `archived`) đều bị tính là `skipped` thay vì tạo bản trùng.
    """
    try:
        params = JobParams.model_validate(job.params)
    except ValueError as exc:
        raise GenerationError(f"Tham số job không hợp lệ: {exc}") from exc
    source = await session.get(Source, job.source_id)
    topic = await session.get(Topic, job.topic_id)
    if source is None or topic is None:
        raise GenerationError("Nguồn hoặc chủ đề của job không còn tồn tại")
    if not source.text.strip():
        raise GenerationError("Nguồn không có văn bản để sinh nội dung")

    chunks = chunk_text(source.text, chunk_chars)
    plan = plan_chunks(params.counts(), len(chunks))
    created = 0
    skipped = 0
    for chunk, counts in zip(chunks, plan, strict=True):
        if not counts:
            continue
        produced = await generate_chunk(
            llm,
            kind=params.kind,
            topic_name=topic.name,
            chunk=chunk,
            counts=counts,
        )
        for entry in produced:
            if await _insert_draft(
                session,
                topic_id=job.topic_id,
                source_id=job.source_id,
                kind=params.kind,
                level=entry["level"],
                content=entry["content"],
            ):
                created += 1
            else:
                skipped += 1
        job.result = {"created": created, "skipped": skipped}
        job.heartbeat_at = now()
        await session.commit()
    return {"created": created, "skipped": skipped}
