import json
import re

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
    text = (
        f"📖 {story.title}\n\n"
        f"Описание:\n{story.description or 'Описание пока не добавлено.'}\n\n"
        f"📚 Сезонов: {seasons_count}\n"
        f"🎬 Серий: {episodes_count}\n"
        f"❤️ Романтические линии: {romance_count}"
    )
    genre = (story.genre or "").strip()
    if genre and genre.lower() not in ("не указан", "визуальная новелла"):
        text += f"\n🏷 Жанр: {genre}"
    return text


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


def classify_choice(choice: Choice) -> tuple[str, str]:
    """
    Returns (emoji_icon, category_name) for visual differentiation:
    - 💔: Ухудшение отношений (разбитое сердце)
    - ❤️: Улучшение отношений / романтика (красное сердце)
    - 🔻: Потеря статов / славы
    - 🟡: Влияние на сюжет / важный выбор / будущее (жёлтый круг)
    - 🟢: Репутация / слава / авторитет (зелёный круг)
    - 🟣: Альтернативный путь / мистика / страсть / тьма (фиолетовый круг)
    - 🔹: Основной путь / логика / дипломатия / свет (синий ромб)
    - 💎: Платный выбор за алмазы
    - ▫️: Нейтральный выбор
    """
    text_all = f"{choice.text or ''} {choice.consequence or ''} {choice.character_effects or ''} {choice.parameter_changes or ''} {choice.future_effects or ''} {choice.tags or ''}".lower()

    # 1. Negative relationship (💔)
    if any(k in text_all for k in [
        "ухудшение отнош", "-отнош", "минус отнош", "затаит обиду", "затаила обиду",
        "разозлит", "оттолкн", "обидит", "конфронтаци", "разочарован", "расстроит",
        "оттолкнете", "охладеет"
    ]):
        return "💔", "rel_neg"

    # 2. Positive relationship / Romance (❤️)
    has_chars = bool(parse_effects_list(choice.character_effects))
    if has_chars or any(k in text_all for k in [
        "улучшение отнош", "+отнош", "+ отношения", "плюс отнош", "любовная сцена",
        "постельная сцена", "поцелу", "поцеловат", "сблизил", "симпати", "интим",
        "ветка", "фаворит", "романт", "понравил", "впечатлил", "сердц"
    ]):
        return "❤️", "rel_pos"

    # 3. Negative stat / Loss of reputation (🔻)
    if any(k in text_all for k in ["минус 1", "минус 2", "минус 3", "-1 слава", "-2 слава", "-1 репутац", "минус слава"]):
        return "🔻", "stat_loss"

    # 4. Story critical / Plot impact (🟡)
    has_futures = bool(parse_effects_list(choice.future_effects))
    if choice.is_critical or has_futures or any(k in text_all for k in [
        "повлияет на", "отразится", "в будущем", "табличка", "важный выбор",
        "развилка", "пригодится", "спасти", "погибн", "выживет", "концовка",
        "финал", "выбор скажется", "выбор требует", "стоит вам", "стоило вам",
        "будет знать", "запомнит", "узнает", "секрет", "жизнь", "смерть"
    ]):
        return "🟡", "story"

    # 5. Parameters / Stats (🟢, 🟣, 🔹)
    has_params = bool(parse_effects_list(choice.parameter_changes))
    has_stat_text = bool(re.search(r"(?:[\+\-]\d+|минус\s+\d+|плюс\s+\d+)\s+[а-яА-Яa-zA-Z]", text_all))
    if has_params or has_stat_text:
        # Reputation / Fame / Respect
        if any(k in text_all for k in ["слава", "репутац", "авторитет", "уважен", "известност", "статус"]):
            return "🟢", "reputation"
        # Alt / Mystical / Emotional stats
        if any(k in text_all for k in [
            "интуиц", "страст", "тьма", "чувств", "магия", "морок", "безумие",
            "хаос", "демон", "анархия", "кровь", "буря", "луна", "тень",
            "цветок", "огонь", "грех", "зло", "шезму"
        ]):
            return "🟣", "stat_alt"
        # Main / Rational / Physical stats
        return "🔹", "stat_main"

    # 6. Paid choices with diamonds (💎)
    if choice.cost_diamonds and choice.cost_diamonds > 0:
        return "💎", "diamond"

    # 7. Neutral choice (▫️)
    return "▫️", "neutral"


def format_choice_item(choice: Choice, spoiler_level: int = 2) -> str:
    """Formats one option under a question with visual emoji badge, bold text, cost, and consequences."""
    icon, _ = classify_choice(choice)

    raw_text = (choice.text or "").strip()
    if not raw_text:
        raw_text = "Выбор без описания"

    clean_text = re.sub(r"^[\s\-\•\—\–]+\s*", "", raw_text)

    cost = choice.cost_diamonds
    cost_str = f" <i>(💎 {pluralize_diamonds(cost)})</i>" if (cost and cost > 0 and str(cost) not in clean_text) else ""

    # Collect parameter and character effects
    extras: list[str] = []
    if choice.parameter_changes and choice.parameter_changes != "[]":
        for p in parse_effects_list(choice.parameter_changes):
            if p not in clean_text:
                extras.append(p)
    if choice.character_effects and choice.character_effects != "[]":
        for c in parse_effects_list(choice.character_effects):
            if c not in clean_text:
                extras.append(f"❤️ {c}")
    if choice.future_effects and choice.future_effects != "[]":
        for f in parse_effects_list(choice.future_effects):
            if f not in clean_text:
                extras.append(f"⚡ {f}")

    extra_str = f" <b>[{' | '.join(extras)}]</b>" if extras else ""

    # Clean consequence if present and not placeholder
    conseq = (choice.consequence or "").strip()
    if conseq and not conseq.lower().startswith("краткий импортированный пункт") and conseq not in clean_text:
        extra_str += f" — <i>{conseq}</i>"

    return f"  {icon} <b>{clean_text}</b>{cost_str}{extra_str}"


def group_episode_choices(choices: list[Choice]) -> list[tuple[str, list[Choice]]]:
    """Groups consecutive choices with the same question (scene_title)."""
    groups: list[tuple[str, list[Choice]]] = []
    current_title: str | None = None
    current_choices: list[Choice] = []

    for c in choices:
        title = (c.scene_title or "").strip()
        if title.lower().startswith("пункт гайда"):
            title = ""

        if title == current_title and current_choices and title:
            current_choices.append(c)
        else:
            if current_choices:
                groups.append((current_title or "", current_choices))
            current_title = title
            current_choices = [c]

    if current_choices:
        groups.append((current_title or "", current_choices))

    return groups


def format_choice_group(group_title: str, group_choices: list[Choice], index: int, spoiler_level: int = 2) -> str:
    """Formats a question block with all its options."""
    title = group_title.strip() if group_title else "Выбор"
    lines = [f"<b>{index}. {title}</b>"]
    for c in group_choices:
        lines.append(format_choice_item(c, spoiler_level))
    return "\n".join(lines)


def format_single_choice(choice: Choice, index: int, spoiler_level: int = 2) -> str:
    """Formats a single choice with human-readable effects, choice.text, and diamond costs."""
    icon, _ = classify_choice(choice)
    lines = []
    title = choice.scene_title or "Выбор"
    lines.append(f"{index}. {title}")

    choice_text = (choice.text or "").strip()
    if choice_text:
        lines.append(f"{icon} {choice_text}")

    rec = (choice.recommended_option or "").strip()
    if rec and rec.lower() != choice_text.lower():
        lines.append(f"👉 {rec}")

    if choice.cost_diamonds and choice.cost_diamonds > 0:
        lines.append("💎 Стоимость:")
        lines.append(f"• {pluralize_diamonds(choice.cost_diamonds)}")

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


GUIDE_LEGEND = (
    "💡 <b>Обозначения:</b>\n"
    "🟡 Сюжет • ❤️ Отношения (💔 Ухудшение)\n"
    "🔹/🟣 Статы • 🟢 Репутация • 💎 Алмазы"
)


def paginate_episode_guide(
    episode: Episode,
    choices: list[Choice],
    spoiler_level: int,
    filter_name: str = "all",
    page: int = 1,
    max_per_page: int = 8,
    max_chars: int = 3800,
) -> tuple[str, int, int]:
    """
    Paginates choices for an episode, grouped by questions, guaranteeing no message exceeds max_chars.
    Returns (page_text, current_page, total_pages).
    """
    story = episode.season.story if episode.season else None
    story_title = story.title if story else "Клуб Романтики"
    season_num = episode.season.number if episode.season else 1
    season_title = episode.season.title if (episode.season and episode.season.title) else f"Сезон {season_num}"
    season_label = season_title if "том" in season_title.lower() else f"Сезон {season_num}"
    title = episode.title or "Без названия"

    legend = f"\n\n{GUIDE_LEGEND}"
    base_header = (
        f"📖 <b>{story_title}</b>\n"
        f"🎬 {season_label} • Серия {episode.number}: {title}"
        f"{legend}"
    )

    if not choices:
        empty_text = f"{base_header}\n\nПока нет выборов для этой серии."
        return empty_text, 1, 1

    # Group choices by question
    groups = group_episode_choices(choices)
    blocks: list[str] = []
    for index, (q_title, group_chs) in enumerate(groups, start=1):
        block = format_choice_group(q_title, group_chs, index, spoiler_level)
        sub_blocks = split_choice_block(block, max_size=max_chars - 400)
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
            f"📖 <b>{story_title}</b>\n"
            f"🎬 {season_label} • Серия {episode.number}: {title} (Страница {current_page}/{total_pages})"
            f"{legend}"
        )
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


def character_text(character: Character, spoiler_level: int = 2) -> str:
    text = (
        f"👤 {character.name}\n\n"
        f"Описание:\n{character.description}\n\n"
        f"Статус: {character.status}\n"
        f"❤️ Романтическая ветка: {'Да' if character.is_love_interest else 'Нет'}\n"
        f"📖 История: {character.story.title}"
    )
    if character.facts:
        text += f"\n\n💡 Факты и особенности:\n{character.facts}"
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
