from alembic import command
from alembic.config import Config

from tests.conftest import BACKEND_DIR


def test_migrations_match_the_models():
    # Fails with "New upgrade operations detected" when a model changed
    # without a new migration.
    command.check(Config(str(BACKEND_DIR / "alembic.ini")))
