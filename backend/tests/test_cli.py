import psycopg

from app.cli import main
from tests.conftest import TEST_DB_URL


def _rows() -> list[tuple[str, str]]:
    with psycopg.connect(TEST_DB_URL.replace("+psycopg", "", 1)) as conn:
        return conn.execute("select username, role from users order by id").fetchall()


def _env(monkeypatch, password: str = "admin-password") -> None:
    monkeypatch.setenv("QUIZZ_DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("QUIZZ_ADMIN_PASSWORD", password)


def test_create_admin_stores_and_reports_the_normalised_username(monkeypatch, capsys):
    _env(monkeypatch)

    assert main(["create-admin", "--username", " Root "]) == 0

    assert _rows() == [("root", "admin")]
    assert "Created admin 'root'" in capsys.readouterr().out


def test_create_admin_refuses_a_duplicate_name_even_with_different_case(
    monkeypatch, capsys
):
    _env(monkeypatch)
    assert main(["create-admin", "--username", "root"]) == 0

    assert main(["create-admin", "--username", "ROOT"]) == 1

    assert "already exists" in capsys.readouterr().err
    assert _rows() == [("root", "admin")]


def test_create_admin_rejects_unusable_usernames_and_passwords(monkeypatch, capsys):
    _env(monkeypatch)
    for name in ("ab", "has space", "UPPER!", "x" * 65):
        assert main(["create-admin", "--username", name]) == 1
        assert "Username must be" in capsys.readouterr().err

    for password in ("short", "x" * 129):
        _env(monkeypatch, password)
        assert main(["create-admin", "--username", "valid"]) == 1
        assert "Password must be 8-128" in capsys.readouterr().err

    assert _rows() == []
