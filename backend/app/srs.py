from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Grade = Literal["again", "hard", "good", "easy"]

INITIAL_EASE = 2.5
MIN_EASE = 1.3
RELEARN_DELAY = timedelta(minutes=10)


@dataclass(frozen=True)
class SrsState:
    due_at: datetime
    interval_days: int = 0
    ease: float = INITIAL_EASE
    reps: int = 0
    lapses: int = 0


def _round(value: float) -> int:
    """Round half up. Python's round() is banker's rounding: round(12.5) == 12."""
    return int(value + 0.5)


def new_state(now: datetime) -> SrsState:
    return SrsState(due_at=now)


def _later(now: datetime, interval_days: int) -> datetime:
    return now + timedelta(days=interval_days)


def schedule(state: SrsState, grade: Grade, now: datetime) -> SrsState:
    """The only place that decides when an item comes back."""
    if grade == "again":
        return SrsState(
            due_at=now + RELEARN_DELAY,
            interval_days=0,
            ease=max(MIN_EASE, state.ease - 0.2),
            reps=0,
            lapses=state.lapses + 1,
        )
    if grade == "hard":
        interval = max(1, _round(state.interval_days * 1.2))
        return SrsState(
            due_at=_later(now, interval),
            interval_days=interval,
            ease=max(MIN_EASE, state.ease - 0.15),
            reps=state.reps,
            lapses=state.lapses,
        )
    if grade == "good":
        if state.reps == 0:
            interval = 1
        elif state.reps == 1:
            interval = 3
        else:
            interval = max(1, _round(state.interval_days * state.ease))
        return SrsState(
            due_at=_later(now, interval),
            interval_days=interval,
            ease=state.ease,
            reps=state.reps + 1,
            lapses=state.lapses,
        )
    # easy: take the good interval, then add a day and a 30% bonus.
    if state.reps == 0:
        base = 1
    elif state.reps == 1:
        base = 3
    else:
        base = max(1, _round(state.interval_days * state.ease))
    interval = max(base + 1, _round(base * 1.3))
    return SrsState(
        due_at=_later(now, interval),
        interval_days=interval,
        ease=state.ease + 0.15,
        reps=state.reps + 1,
        lapses=state.lapses,
    )
