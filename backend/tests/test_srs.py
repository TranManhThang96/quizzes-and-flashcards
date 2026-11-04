from datetime import UTC, datetime, timedelta

import pytest

from app.srs import SrsState, new_state, schedule

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def test_a_new_bad_card_has_the_documented_defaults():
    state = new_state(NOW)

    assert (state.interval_days, state.ease, state.reps, state.lapses) == (0, 2.5, 0, 0)
    assert state.due_at == NOW


def test_good_starts_at_one_then_three_days():
    first = schedule(new_state(NOW), "good", NOW)
    second = schedule(first, "good", NOW)

    assert (first.interval_days, first.reps) == (1, 1)
    assert first.due_at == NOW + timedelta(days=1)
    assert (second.interval_days, second.reps) == (3, 2)


def test_good_multiplies_by_ease_and_rounds_half_up():
    state = SrsState(due_at=NOW, interval_days=5, ease=2.5, reps=2)

    updated = schedule(state, "good", NOW)

    # 5 * 2.5 = 12.5 must round to 13, not banker's 12.
    assert updated.interval_days == 13
    assert updated.ease == 2.5
    assert updated.due_at == NOW + timedelta(days=13)


def test_easy_adds_a_day_then_a_thirty_percent_bonus():
    state = SrsState(due_at=NOW, interval_days=5, ease=2.5, reps=2)

    updated = schedule(state, "easy", NOW)

    # good interval is 13; easy takes max(13 + 1, round(13 * 1.3)) = 17.
    assert updated.interval_days == 17
    assert updated.ease == pytest.approx(2.65)
    assert updated.reps == 3


def test_again_resets_the_card_and_comes_back_in_ten_minutes():
    state = SrsState(due_at=NOW, interval_days=30, ease=2.5, reps=5, lapses=1)

    updated = schedule(state, "again", NOW)

    assert updated.due_at == NOW + timedelta(minutes=10)
    assert (updated.interval_days, updated.reps, updated.lapses) == (0, 0, 2)
    assert updated.ease == pytest.approx(2.3)


def test_hard_keeps_reps_and_clamps_ease_at_one_point_three():
    state = SrsState(due_at=NOW, interval_days=2, ease=1.35, reps=4)

    updated = schedule(state, "hard", NOW)

    assert updated.interval_days == 2
    assert updated.reps == 4
    assert updated.ease == pytest.approx(1.3)


def test_a_new_card_graded_easy_starts_at_two_days():
    updated = schedule(new_state(NOW), "easy", NOW)

    # good would be 1 day; easy takes max(2, round(1.3)) = 2.
    assert updated.interval_days == 2


def test_a_new_card_graded_hard_starts_at_one_day():
    updated = schedule(new_state(NOW), "hard", NOW)

    assert updated.interval_days == 1
    assert updated.reps == 0
