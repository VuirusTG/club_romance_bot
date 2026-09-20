from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories.content import global_search


async def format_search_results(session: AsyncSession, query: str) -> str:
    results = await global_search(session, query)
    lines = [f"🔎 Результаты поиска: {query}", ""]

    if results["stories"]:
        lines.append("📖 Истории:")
        lines.extend(f"• {story.title}" for story in results["stories"])
        lines.append("")

    if results["characters"]:
        lines.append("👤 Персонажи:")
        lines.extend(f"• {character.name}" for character in results["characters"])
        lines.append("")

    if results["episodes"]:
        lines.append("🎬 Серии:")
        lines.extend(f"• Серия {episode.number}: {episode.title or 'Без названия'}" for episode in results["episodes"])
        lines.append("")

    if results["choices"]:
        lines.append("🧭 Найдено в гайдах:")
        lines.extend(f"• {choice.text[:80]}" for choice in results["choices"])

    if len(lines) == 2:
        lines.append("Ничего не нашлось. Попробуй другое название или имя персонажа.")

    return "\n".join(lines)

