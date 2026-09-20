import asyncio
from datetime import datetime

from sqlalchemy import delete, select

from bot.database.database import AsyncSessionFactory, init_db
from bot.database.models import UpdatePost


OFFICIAL_UPDATES = [
    {
        "title": "Техническое обновление 1.0.51600 доступно на iOS",
        "body": (
            "Официальный канал сообщил, что техническое обновление версии 1.0.51600 стало доступно на iOS. "
            "Чтобы изменения вступили в силу, нужно обновить приложение до последней версии."
        ),
        "game_version": "1.0.51600",
        "source_name": "Официальный Telegram-канал «Клуб Романтики — Мои Истории»",
        "source_url": "https://t.me/s/official_romanceclub?before=5732",
        "created_at": datetime(2026, 7, 1),
    },
    {
        "title": "График технических обновлений на июль и сентябрь 2026",
        "body": (
            "В официальном канале описан перенос части запланированных функций. На июль заявлены расширенные "
            "возможности персонализации профиля, сохранение образов аватара и отдельный гардероб для фаворитов. "
            "На сентябрь запланированы изменения календаря наград."
        ),
        "game_version": None,
        "source_name": "Официальный Telegram-канал «Клуб Романтики — Мои Истории»",
        "source_url": "https://t.me/s/official_romanceclub?before=5732",
        "created_at": datetime(2026, 6, 30),
    },
    {
        "title": "Обновление 1.0.51500 вышло для Android, iOS и ПК/Steam",
        "body": (
            "Официальный канал сообщил о выходе версии 1.0.51500 для Android, iOS и ПК/Steam. "
            "Для доступа к новым историям разработчики рекомендуют обновить приложение через магазин."
        ),
        "game_version": "1.0.51500",
        "source_name": "Официальный Telegram-канал «Клуб Романтики — Мои Истории»",
        "source_url": "https://t.me/s/official_romanceclub?before=5509",
        "created_at": datetime(2026, 3, 1),
    },
    {
        "title": "App Store: обновление с новыми сериями",
        "body": (
            "В описании версии 1.0.47550 в App Store перечислены новые серии для Chasing You 2, "
            "W: Time Catcher, Kali — Flame of Samsara, And the Haze Will Take Us, The Thunderstorms Saga, "
            "Shakespeare's Code, The Missing, Advent No. 3, Code Blue, Where Love Burns Eternal, "
            "Heaven's Secret 3 и The Parallel Universes Bureau Vol. 2."
        ),
        "game_version": "1.0.47550",
        "source_name": "App Store / Your Story Interactive",
        "source_url": "https://apps.apple.com/us/app/romance-club-stories-i-play/id1300588558",
        "created_at": datetime(2025, 11, 17),
    },
]


async def seed_updates(session) -> None:
    await session.execute(delete(UpdatePost).where(UpdatePost.title == "Добавлена тестовая история"))
    for item in OFFICIAL_UPDATES:
        existing = await session.scalar(select(UpdatePost).where(UpdatePost.title == item["title"]))
        if existing is None:
            session.add(UpdatePost(**item, is_published=True))
        else:
            existing.body = item["body"]
            existing.source_name = item["source_name"]
            existing.source_url = item["source_url"]
            existing.game_version = item["game_version"]
            existing.created_at = item["created_at"]


async def seed() -> None:
    await init_db()
    async with AsyncSessionFactory() as session:
        await seed_updates(session)
        await session.commit()
        print(f"Seed data inserted/updated: {len(OFFICIAL_UPDATES)} official game updates.")


if __name__ == "__main__":
    asyncio.run(seed())

