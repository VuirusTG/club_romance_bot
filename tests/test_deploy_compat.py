from bot.database.database import normalize_database_url


def test_normalize_database_url_empty():
    assert normalize_database_url("") == "sqlite+aiosqlite:///./club_romance.db"


def test_normalize_database_url_postgres():
    render_url = "postgres://user:pass@dpg-xxxx.render.com/dbname"
    normalized = normalize_database_url(render_url)
    assert normalized == "postgresql+asyncpg://user:pass@dpg-xxxx.render.com/dbname"


def test_normalize_database_url_postgresql():
    pg_url = "postgresql://user:pass@dpg-xxxx.render.com/dbname"
    normalized = normalize_database_url(pg_url)
    assert normalized == "postgresql+asyncpg://user:pass@dpg-xxxx.render.com/dbname"


def test_normalize_database_url_sqlite():
    sqlite_url = "sqlite:///./test.db"
    assert normalize_database_url(sqlite_url) == "sqlite+aiosqlite:///./test.db"
    aiosqlite_url = "sqlite+aiosqlite:///./test.db"
    assert normalize_database_url(aiosqlite_url) == "sqlite+aiosqlite:///./test.db"
