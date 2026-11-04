from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import day_start
from app.models import Item, ReviewLog, ReviewState, Topic, User
from app.srs import Grade, SrsState, new_state, schedule


async def apply_review(
    db: AsyncSession,
    *,
    user_id: int,
    item_id: int,
    grade: Grade,
    context: str,
    now: datetime,
) -> ReviewState:
    """Update one review state and append the log. The caller commits."""
    # Two answers for the same card (a double tap, or the exam and study
    # screens at once) would otherwise both insert a missing row, or both
    # read the same old values and lose one transition. The lock is released
    # when the caller commits.
    await db.execute(select(func.pg_advisory_xact_lock(user_id, item_id)))

    item = await db.get(Item, item_id)
    if item is None:
        raise LookupError(item_id)

    row = await db.get(ReviewState, (user_id, item_id))
    current = (
        SrsState(
            due_at=row.due_at,
            interval_days=row.interval_days,
            ease=row.ease,
            reps=row.reps,
            lapses=row.lapses,
        )
        if row is not None
        else new_state(now)
    )
    updated = schedule(current, grade, now)
    if row is None:
        row = ReviewState(
            user_id=user_id,
            item_id=item_id,
            due_at=updated.due_at,
            interval_days=updated.interval_days,
            ease=updated.ease,
            reps=updated.reps,
            lapses=updated.lapses,
        )
        db.add(row)
    else:
        row.due_at = updated.due_at
        row.interval_days = updated.interval_days
        row.ease = updated.ease
        row.reps = updated.reps
        row.lapses = updated.lapses

    db.add(
        ReviewLog(
            user_id=user_id,
            item_id=item_id,
            grade=grade,
            correct=grade != "again",
            context=context,
            at=now,
        )
    )
    return row


@dataclass(frozen=True)
class QueueCard:
    item: Item
    topic_name: str
    due_at: datetime | None
    is_new: bool


@dataclass(frozen=True)
class Stats:
    due_today: int
    new_remaining: int
    reviews_today: int
    accuracy_7d: float
    streak_days: int


async def introduced_today(
    db: AsyncSession, user_id: int, now: datetime, tz: ZoneInfo
) -> int:
    """First-time states created today, whatever introduced them.

    A state created by an exam submit also counts: the item is no longer new,
    so it must not also be handed out as a new study card the same day.
    """
    start = day_start(now, tz)
    stmt = (
        select(func.count())
        .select_from(ReviewState)
        .where(ReviewState.user_id == user_id, ReviewState.created_at >= start)
    )
    return (await db.execute(stmt)).scalar_one()


async def _due_cards(
    db: AsyncSession,
    *,
    user_id: int,
    now: datetime,
    limit: int,
    topic_id: int | None,
    level: str | None,
    lapses_only: bool,
) -> list[QueueCard]:
    if limit <= 0:
        return []
    stmt = (
        select(Item, ReviewState, Topic.name)
        .join(ReviewState, ReviewState.item_id == Item.id)
        .join(Topic, Topic.id == Item.topic_id)
        .where(
            ReviewState.user_id == user_id,
            ReviewState.due_at <= now,
            Item.status == "published",
        )
        .order_by(ReviewState.due_at, Item.id)
        .limit(limit)
    )
    if topic_id is not None:
        stmt = stmt.where(Item.topic_id == topic_id)
    if level is not None:
        stmt = stmt.where(Item.level == level)
    if lapses_only:
        stmt = stmt.where(ReviewState.lapses > 0)
    rows = (await db.execute(stmt)).all()
    return [
        QueueCard(
            item=row[0],
            topic_name=row[2],
            due_at=row[1].due_at,
            is_new=False,
        )
        for row in rows
    ]


async def _new_cards(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int,
    topic_id: int | None,
    level: str | None,
) -> list[QueueCard]:
    if limit <= 0:
        return []
    stmt = (
        select(Item, Topic.name)
        .join(Topic, Topic.id == Item.topic_id)
        .outerjoin(
            ReviewState,
            (ReviewState.item_id == Item.id) & (ReviewState.user_id == user_id),
        )
        .where(ReviewState.user_id.is_(None), Item.status == "published")
        .order_by(func.random())
        .limit(limit)
    )
    if topic_id is not None:
        stmt = stmt.where(Item.topic_id == topic_id)
    if level is not None:
        stmt = stmt.where(Item.level == level)
    rows = (await db.execute(stmt)).all()
    return [
        QueueCard(item=row[0], topic_name=row[1], due_at=None, is_new=True)
        for row in rows
    ]


async def build_queue(
    db: AsyncSession,
    *,
    user: User,
    now: datetime,
    tz: ZoneInfo,
    limit: int,
    topic_id: int | None = None,
    level: str | None = None,
) -> list[QueueCard]:
    due = await _due_cards(
        db,
        user_id=user.id,
        now=now,
        limit=limit,
        topic_id=topic_id,
        level=level,
        lapses_only=False,
    )
    introduced = await introduced_today(db, user.id, now, tz)
    quota = max(0, min(limit - len(due), user.daily_new_limit - introduced))
    new = await _new_cards(
        db, user_id=user.id, limit=quota, topic_id=topic_id, level=level
    )
    return due + new


async def wrong_cards(
    db: AsyncSession, *, user_id: int, now: datetime, limit: int
) -> list[QueueCard]:
    return await _due_cards(
        db,
        user_id=user_id,
        now=now,
        limit=limit,
        topic_id=None,
        level=None,
        lapses_only=True,
    )


async def stats(
    db: AsyncSession,
    *,
    user: User,
    now: datetime,
    tz: ZoneInfo,
) -> Stats:
    start = day_start(now, tz)
    due_today = (
        await db.execute(
            select(func.count())
            .select_from(ReviewState)
            .join(Item, Item.id == ReviewState.item_id)
            .where(
                ReviewState.user_id == user.id,
                ReviewState.due_at <= now,
                Item.status == "published",
            )
        )
    ).scalar_one()
    reviews_today = (
        await db.execute(
            select(func.count())
            .select_from(ReviewLog)
            .where(ReviewLog.user_id == user.id, ReviewLog.at >= start)
        )
    ).scalar_one()
    week_ago = now - timedelta(days=7)
    week_total, week_correct = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(ReviewLog.correct.is_(True)),
            ).where(ReviewLog.user_id == user.id, ReviewLog.at >= week_ago)
        )
    ).one()
    local_day = func.date(func.timezone(tz.key, ReviewLog.at))
    logged_days = set(
        (
            await db.execute(
                select(local_day).where(ReviewLog.user_id == user.id).distinct()
            )
        )
        .scalars()
        .all()
    )
    cursor = now.astimezone(tz).date()
    if cursor not in logged_days:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor in logged_days:
        streak += 1
        cursor -= timedelta(days=1)
    introduced = await introduced_today(db, user.id, now, tz)
    return Stats(
        due_today=due_today,
        new_remaining=max(0, user.daily_new_limit - introduced),
        reviews_today=reviews_today,
        accuracy_7d=(week_correct / week_total) if week_total else 0.0,
        streak_days=streak,
    )
