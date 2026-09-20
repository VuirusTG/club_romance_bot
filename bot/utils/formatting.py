import json

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


def pluralize_diamonds(n: int) -> str:
    """Returns correct Russian plural form for diamonds (e.g. 1 алмаз, 23 алмаза, 10 алмазов)."""
    if 11 <= n % 100 <= 14:
        return f"{n} алмазов"
    last = n % 10
    if last == 1:
        return f"{n} алмаз"
    if 2 <= last <= 4:
        return f"{n} алмаза"
    return f"{n} алмазов"


def parse_effects_list(value: str | list | None) -> list[str]:
    """Parses JSON list/dict or plain string effects into a clean list of strings."""
    if not value:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        val = value.strip()
        if not val or val in ("[]", "{}", "null", '""'):
            return []
        if (val.startswith("[") and val.endswith("]")) or (val.startswith("{") and val.endswith("}")):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    items = parsed
                elif isinstance(parsed, dict):
                    items = [f"{k}: {v}" for k, v in parsed.items()]
                else:
                    items = [str(parsed)]
            except Exception:
                items = [val]
        else:
            items = [val]
    else:
        items = [str(value)]

    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            clean = item.strip()
            if clean.startswith("• "):
                clean = clean[2:].strip()
            elif clean.startswith("- "):
                clean = clean[2:].strip()
            if clean:
                result.append(clean)
        elif item is not None:
            result.append(str(item).strip())
    return result


def split_choice_block(block: str, max_size: int = 3000) -> list[str]:
    """Splits a single huge choice block into multiple parts without truncating."""
    if len(block) <= max_size:
        return [block]

    lines = block.split("\n")
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in lines:
        if current_len + len(line) + 1 > max_size and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0

        while len(line) > max_size:
            part = line[:max_size]
            chunks.append(part)
            line = line[max_size:]

        current_lines.append(line)
        current_len += len(line) + 1

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def format_single_choice(choice: Choice, index: int, spoiler_level: int) -> str:
    """Formats a single choice with human-readable effects, choice.text, and diamond costs."""
    lines = []
    title = choice.scene_title or "Выбор"
    lines.append(f"{index}. {title}")

    choice_text = (choice.text or "").strip()
    if choice_text:
        lines.append(choice_text)

    rec = (choice.recommended_option or "").strip()
    if rec and rec.lower() != choice_text.lower():
        lines.append(f"👉 {rec}")

    if choice.cost_diamonds and choice.cost_diamonds > 0:
        lines.append("💎 Стоимость:")
        lines.append(f"• {pluralize_diamonds(choice.cost_diamonds)}")

    is_hidden = choice.spoiler_level > spoiler_level
    if is_hidden:
        lines.append("🔒 Последствие скрыто настройками спойлеров.")
    else:
        if choice.consequence and choice.consequence.strip():
            conseq_items = parse_effects_list(choice.consequence)
            if len(conseq_items) > 1:
                lines.append("🎯 Последствия:")
                for item in conseq_items:
                    lines.append(f"• {item}")
            elif conseq_items:
                lines.append(f"🎯 Последствие: {conseq_items[0]}")
            else:
                lines.append(f"🎯 Последствие: {choice.consequence.strip()}")

        param_items = parse_effects_list(choice.parameter_changes)
        if param_items:
            lines.append("📊 Параметры:")
            for p in param_items:
                lines.append(f"• {p}")

        char_items = parse_effects_list(choice.character_effects)
        if char_items:
            lines.append("❤️ Отношения:")
            for c in char_items:
                lines.append(f"• {c}")

        fut_items = parse_effects_list(choice.future_effects)
        if fut_items:
            lines.append("🔮 В будущем:")
            for f in fut_items:
                lines.append(f"• {f}")

    if choice.requirements and choice.requirements.strip():
        req_items = parse_effects_list(choice.requirements)
        if len(req_items) > 1:
            lines.append("📋 Условия:")
            for req in req_items:
                lines.append(f"• {req}")
        elif req_items:
            lines.append(f"📋 Условия: {req_items[0]}")
        else:
            lines.append(f"📋 Условия: {choice.requirements.strip()}")

    return "\n".join(lines)


def paginate_episode_guide(
    episode: Episode,
    choices: list[Choice],
    spoiler_level: int,
    filter_name: str = "all",
    page: int = 1,
    max_per_page: int = 10,
    max_chars: int = 3800,
) -> tuple[str, int, int]:
    """
    Paginates choices for an episode, guaranteeing no message exceeds max_chars.
    Returns (page_text, current_page, total_pages).
    """
    story = episode.season.story if episode.season else None
    story_title = story.title if story else "Клуб Романтики"
    season_num = episode.season.number if episode.season else 1
    season_title = episode.season.title if (episode.season and episode.season.title) else f"Сезон {season_num}"
    season_label = season_title if "том" in season_title.lower() else f"Сезон {season_num}"
    title = episode.title or "Без названия"

    intro = episode.guide_intro or episode.summary or "Гайд для серии пока заполняется."
    header_lines = [
        f"📖 История: {story_title}",
        f"{season_label} • Серия {episode.number}: {title}",
        "",
        intro,
    ]
    if episode.guide_source_name:
        header_lines.extend(["", f"Источник: {episode.guide_source_name}"])
    if episode.guide_source_url:
        header_lines.append("Подробное прохождение доступно по кнопке под сообщением.")
    header_lines.extend(["", "Гайд:"])
    base_header = "\n".join(header_lines)

    if not choices:
        empty_text = f"{base_header}\n\nПока нет выборов для выбранного фильтра."
        return empty_text, 1, 1

    blocks: list[str] = []
    for index, choice in enumerate(choices, start=1):
        block = format_single_choice(choice, index, spoiler_level)
        sub_blocks = split_choice_block(block, max_size=max_chars - 600)
        blocks.extend(sub_blocks)

    pages_blocks: list[list[str]] = []
    current_page_blocks: list[str] = []
    estimated_header_len = len(base_header) + 40
    current_len = estimated_header_len

    for b in blocks:
        b_len = len(b) + 2
        if current_page_blocks and (len(current_page_blocks) >= max_per_page or current_len + b_len > max_chars):
            pages_blocks.append(current_page_blocks)
            current_page_blocks = []
            current_len = estimated_header_len
        current_page_blocks.append(b)
        current_len += b_len

    if current_page_blocks:
        pages_blocks.append(current_page_blocks)

    total_pages = max(1, len(pages_blocks))
    current_page = max(1, min(page, total_pages))

    selected_blocks = pages_blocks[current_page - 1]
    if total_pages > 1:
        page_header = (
            f"📖 История: {story_title}\n"
            f"{season_label} • Серия {episode.number}: {title} (Страница {current_page}/{total_pages})\n\n"
            f"{intro}"
        )
        if episode.guide_source_name:
            page_header += f"\n\nИсточник: {episode.guide_source_name}"
        if episode.guide_source_url:
            page_header += "\nПодробное прохождение доступно по кнопке под сообщением."
        page_header += "\n\nГайд:"
    else:
        page_header = base_header

    full_page_text = f"{page_header}\n\n" + "\n\n".join(selected_blocks)
    return full_page_text, current_page, total_pages


def episode_guide_text(
    episode: Episode,
    choices: list[Choice],
    spoiler_level: int,
    filter_name: str = "all",
    page: int = 1,
) -> str:
    text, _, _ = paginate_episode_guide(episode, choices, spoiler_level, filter_name, page=page)
    return text


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
