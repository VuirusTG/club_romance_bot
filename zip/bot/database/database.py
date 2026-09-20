from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event, text

from bot.config import get_settings
from bot.database.models import Base


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            columns = await connection.execute(text("PRAGMA table_info(updates)"))
            existing_columns = {row[1] for row in columns.fetchall()}
            migrations = {
                "source_name": "ALTER TABLE updates ADD COLUMN source_name VARCHAR(255)",
                "source_url": "ALTER TABLE updates ADD COLUMN source_url VARCHAR(500)",
                "game_version": "ALTER TABLE updates ADD COLUMN game_version VARCHAR(50)",
            }
            for column_name, statement in migrations.items():
                if column_name not in existing_columns:
                    await connection.execute(text(statement))

            table_migrations = {
                "stories": {
                    "guide_source_name": "ALTER TABLE stories ADD COLUMN guide_source_name VARCHAR(255)",
                    "guide_source_url": "ALTER TABLE stories ADD COLUMN guide_source_url VARCHAR(500)",
                },
                "episodes": {
                    "guide_source_name": "ALTER TABLE episodes ADD COLUMN guide_source_name VARCHAR(255)",
                    "guide_source_url": "ALTER TABLE episodes ADD COLUMN guide_source_url VARCHAR(500)",
                },
            }
            for table_name, table_columns in table_migrations.items():
                rows = await connection.execute(text(f"PRAGMA table_info({table_name})"))
                existing = {row[1] for row in rows.fetchall()}
                for column_name, statement in table_columns.items():
                    if column_name not in existing:
                        await connection.execute(text(statement))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        yield session
