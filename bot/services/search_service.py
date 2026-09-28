from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories.content import global_search


async def search_results_payload(session: AsyncSession, query: str) -> tuple[str, InlineKeyboardMarkup]:
    results = await global_search(session, query)
    lines = [f"🔎 Результаты поиска по запросу «<b>{query}</b>»:", ""]
    rows: list[list[InlineKeyboardButton]] = []

    has_results = False

    if results["stories"]:
        has_results = True
        lines.append("📖 <b>Истории:</b>")
        for story in results["stories"]:
            lines.append(f"• {story.title}")
            rows.append([InlineKeyboardButton(text=f"📖 {story.title}", callback_data=f"story:{story.id}")])
        lines.append("")

    if results["characters"]:
        has_results = True
        lines.append("👤 <b>Персонажи:</b>")
        for character in results["characters"]:
            lines.append(f"• {character.name}")
            rows.append([InlineKeyboardButton(text=f"👤 {character.name}", callback_data=f"char:{character.id}")])
        lines.append("")

    if results["episodes"]:
        has_results = True
        lines.append("🎬 <b>Серии:</b>")
        for episode in results["episodes"]:
            ep_title = f"Серия {episode.number}: {episode.title or 'Без названия'}"
            lines.append(f"• {ep_title}")
            rows.append([InlineKeyboardButton(text=f"🎬 {ep_title[:38]}", callback_data=f"guide:{episode.id}:1:1")])
        lines.append("")

    if results["choices"]:
        has_results = True
        lines.append("🧭 <b>Найдено в гайдах:</b>")
        for choice in results["choices"]:
            desc = choice.scene_title or choice.text[:50]
            lines.append(f"• {choice.text[:80]}")
            if choice.episode_id:
                rows.append([InlineKeyboardButton(text=f"🧭 {desc[:35]}...", callback_data=f"guide:{choice.episode_id}:1:1")])

    if not has_results:
        lines = [
            f"🔎 По запросу «<b>{query}</b>» ничего не нашлось.",
            "",
            "Попробуй ввести другое название истории или имя персонажа.",
        ]

    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")])
    return "\n".join(lines).strip(), InlineKeyboardMarkup(inline_keyboard=rows)


async def format_search_results(session: AsyncSession, query: str) -> str:
    text, _ = await search_results_payload(session, query)
    return text
