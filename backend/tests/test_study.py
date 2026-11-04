from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import update

from app.models import ReviewLog, ReviewState, User
from app.reviews import stats
from tests.conftest import login

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)  # 10:00 in Ho Chi Minh City


async def _login(client, make_user, username="alice"):
    user = await make_user(username, "correct-horse")
    await login(client, username, "correct-horse")
    return user


async def test_queue_returns_new_cards_up_to_the_daily_limit(
    client, make_user, make_topic, make_item, app
):
    user = await _login(client, make_user)
    topic = await make_topic("Toán")
    for _ in range(3):
        await make_item(topic.id, status="published")

    async with app.state.sessionmaker() as s:
        await s.execute(
            update(User).where(User.id == user.id).values(daily_new_limit=2)
        )
        await s.commit()

    first = await client.get("/api/study/queue")
    assert first.status_code == 200
    cards = first.json()
    assert len(cards) == 2 and all(card["is_new"] for card in cards)

    for card in cards:
        await client.post(
            "/api/review/answer", json={"item_id": card["item_id"], "grade": "good"}
        )

    # Both introductions count against today's quota even though they are due
    # tomorrow; the third card must wait for a new day.
    assert (await client.get("/api/study/queue")).json() == []


async def test_queue_puts_due_cards_first_and_honours_filters(
    client, make_user, make_topic, make_item, app
):
    user = await _login(client, make_user)
    math = await make_topic("Toán")
    english = await make_topic("Anh")
    due_math = await make_item(math.id, status="published", level="easy")
    due_english = await make_item(english.id, status="published", level="hard")
    draft = await make_item(math.id, status="draft")
    archived = await make_item(math.id, status="archived")
    async with app.state.sessionmaker() as s:
        for item in (due_math, due_english):
            s.add(
                ReviewState(
                    user_id=user.id,
                    item_id=item.id,
                    due_at=NOW - timedelta(hours=1),
                )
            )
        await s.commit()

    everything = (await client.get("/api/study/queue")).json()
    assert [card["item_id"] for card in everything] == [due_math.id, due_english.id]
    assert all(not card["is_new"] for card in everything)

    filtered = (
        await client.get("/api/study/queue", params={"topic_id": english.id})
    ).json()
    assert [card["item_id"] for card in filtered] == [due_english.id]

    by_level = (await client.get("/api/study/queue", params={"level": "easy"})).json()
    assert [card["item_id"] for card in by_level] == [due_math.id]
    assert draft.id not in [card["item_id"] for card in everything]
    assert archived.id not in [card["item_id"] for card in everything]


async def test_wrong_queue_only_lists_due_cards_with_lapses(
    client, make_user, make_topic, make_item, app
):
    user = await _login(client, make_user)
    topic = await make_topic("Toán")
    wrong = await make_item(topic.id, status="published")
    clean = await make_item(topic.id, status="published", kind="vocab")
    async with app.state.sessionmaker() as s:
        s.add(
            ReviewState(
                user_id=user.id,
                item_id=wrong.id,
                due_at=NOW - timedelta(minutes=1),
                lapses=2,
            )
        )
        s.add(
            ReviewState(
                user_id=user.id,
                item_id=clean.id,
                due_at=NOW - timedelta(minutes=1),
                lapses=0,
            )
        )
        await s.commit()

    cards = (await client.get("/api/review/wrong")).json()

    assert [card["item_id"] for card in cards] == [wrong.id]


async def test_stats_and_streak_use_the_configured_timezone(
    client, make_user, make_topic, make_item, app
):
    user = await _login(client, make_user)
    topic = await make_topic("Toán")
    item = await make_item(topic.id, status="published")
    # 17:30 UTC on Nov 2 is 00:30 on Nov 3 in Ho Chi Minh City.
    boundary = datetime(2026, 11, 2, 17, 30, tzinfo=UTC)
    async with app.state.sessionmaker() as s:
        s.add(
            ReviewLog(
                user_id=user.id,
                item_id=item.id,
                grade="good",
                correct=True,
                context="study",
                at=boundary,
            )
        )
        s.add(
            ReviewLog(
                user_id=user.id,
                item_id=item.id,
                grade="again",
                correct=False,
                context="study",
                at=datetime(2026, 11, 2, 2, 0, tzinfo=UTC),
            )
        )
        s.add(
            ReviewState(
                user_id=user.id,
                item_id=item.id,
                due_at=NOW - timedelta(hours=2),
            )
        )
        await s.commit()

    async with app.state.sessionmaker() as s:
        result = await stats(
            s, user=user, now=datetime(2026, 11, 3, 4, 0, tzinfo=UTC), tz=TZ
        )

    assert result.due_today == 1
    assert result.reviews_today == 1
    assert result.accuracy_7d == 0.5
    # Nov 2 UTC 02:00 is Nov 2 local, so the streak is Nov 2 -> Nov 3 = 2 days.
    assert result.streak_days == 2


async def test_study_endpoints_require_login(client):
    for path in ("/api/study/queue", "/api/review/wrong", "/api/stats"):
        assert (await client.get(path)).status_code == 401
