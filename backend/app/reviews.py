from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, ReviewLog, ReviewState
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
