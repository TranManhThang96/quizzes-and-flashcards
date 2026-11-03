from app.config import Settings


def test_origin_setting_ignores_a_trailing_slash():
    # A trailing slash would never match a browser's Origin header and every
    # write request would be rejected with 403.
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        app_origin="https://quizz.test/",
    )

    assert settings.app_origin == "https://quizz.test"
