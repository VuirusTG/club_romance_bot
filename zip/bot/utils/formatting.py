from bot.database.models import Character, Choice, Episode, Story


SPOILER_LABELS = {
    0: "🟢 Без спойлеров",
    1: "🟡 Небольшие спойлеры",
    2: "🔴 Серьёзные спойлеры",
}


def story_text(story: Story) -> str:
    seasons_count = len(story.seasons)
    episodes_count = sum(len(season.episodes) for season in story.seasons)
    romance_count = sum(1 for character in story.characters if character.is_love_interest)
    return (
        f"📖 {story.title}\n\n"
        f"Описание:\n{story.description or 'Описание пока не добавлено.'}\n\n"
        f"📚 Сезонов: {seasons_count}\n"
        f"🎬 Серий: {episodes_count}\n"
        f"❤️ Романтические линии: {romance_count}\n"
        f"🏷 Жанр: {story.genre or 'не указан'}"
    )


def episode_guide_text(episode: Episode, choices: list[Choice], spoiler_level: int, filter_name: str = "all") -> str:
    story = episode.season.story
    title = episode.title or "Без названия"
    lines = [
        f"📖 История: {story.title}",
        f"Сезон {episode.season.number} • Серия {episode.number}: {title}",
        "",
        episode.guide_intro or episode.summary or "Гайд для серии пока заполняется.",
    ]
    if episode.guide_source_name:
        lines.extend(["", f"Источник: {episode.guide_source_name}"])
    if episode.guide_source_url:
        lines.append("Подробное прохождение доступно по кнопке под сообщением.")
    lines.extend(["", "Гайд:"])

    if not choices:
        lines.append("Пока нет выборов для выбранного фильтра.")
        return "\n".join(lines)

    for index, choice in enumerate(choices, start=1):
        is_hidden = choice.spoiler_level > spoiler_level
        lines.append("")
        lines.append(f"{index}. {choice.scene_title or 'Выбор'}")
        lines.append(f"👉 {choice.recommended_option}")
        if choice.cost_diamonds:
            lines.append(f"Стоимость: {choice.cost_diamonds} 💎")
        if is_hidden:
            lines.append("🔒 Последствие скрыто настройками спойлеров.")
        else:
            if choice.consequence:
                lines.append(f"Последствие: {choice.consequence}")
            if choice.parameter_changes:
                lines.append(f"📊 Параметры: {choice.parameter_changes}")
            if choice.character_effects:
                lines.append(f"❤️ Персонажи: {choice.character_effects}")
            if choice.future_effects:
                lines.append(f"Дальше: {choice.future_effects}")
        if choice.requirements:
            lines.append(f"Условия: {choice.requirements}")

    return "\n".join(lines)


def character_text(character: Character, spoiler_level: int) -> str:
    is_hidden = character.spoiler_level > spoiler_level
    text = (
        f"👤 {character.name}\n\n"
        f"Описание:\n{character.description}\n\n"
        f"Статус: {character.status}\n"
        f"❤️ Романтическая ветка: {'Да' if character.is_love_interest else 'Нет'}\n"
        f"📖 История: {character.story.title}\n"
        f"Уровень спойлеров: {SPOILER_LABELS.get(character.spoiler_level, 'не указан')}"
    )
    if character.facts:
        text += "\n\n" + ("🔒 Дополнительная информация скрыта." if is_hidden else character.facts)
    return text


def help_text() -> str:
    return (
        "ℹ️ Помощь\n\n"
        "Бот помогает быстро найти историю, серию и нужный выбор.\n\n"
        "/start — главное меню\n"
        "/search — поиск\n"
        "/favorites — избранное\n"
        "/settings — настройки\n"
        "/updates — обновления\n"
        "/admin — админ-панель"
    )
