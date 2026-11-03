import asyncio

import pytest
from sqlalchemy import func, select

from app.models import User
from app.security import verify_password
from app.users import UsernameTaken, create_user


async def test_password_is_stored_as_an_argon2_hash(app):
    async with app.state.sessionmaker() as s:
        user = await create_user(s, username="alice", password="correct-horse")
        await s.commit()

    assert user.password_hash.startswith("$argon2id$")
    assert "correct-horse" not in user.password_hash
    assert verify_password("correct-horse", user.password_hash)


async def test_duplicate_username_raises_and_the_session_stays_usable(app):
    async with app.state.sessionmaker() as s:
        await create_user(s, username="alice", password="correct-horse")
        await s.commit()

        with pytest.raises(UsernameTaken):
            await create_user(s, username="alice", password="another-pass")

        count = (await s.execute(select(func.count()).select_from(User))).scalar_one()
        assert count == 1


async def test_concurrent_creation_of_one_name_yields_exactly_one_user(app):
    async def attempt(password: str) -> bool:
        async with app.state.sessionmaker() as s:
            try:
                await create_user(s, username="alice", password=password)
                await s.commit()
            except UsernameTaken:
                return False
            return True

    results = await asyncio.gather(attempt("first-pass-1"), attempt("second-pass-2"))

    assert sorted(results) == [False, True]
    async with app.state.sessionmaker() as s:
        count = (await s.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1
