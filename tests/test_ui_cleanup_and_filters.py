import pytest
import sqlite3
from bot.database.models import Character, Choice, Episode, Season, Story
from bot.handlers.settings import _settings_keyboard
from bot.keyboards.guides import guide_filters
from bot.keyboards.main import main_menu
from bot.keyboards.stories import story_card
from bot.utils.formatting import character_text, story_text


def test_main_menu_has_no_duplicate_guides():
    kb = main_menu(is_admin=False)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "📖 Истории" in all_texts
    assert "🧭 Гайды" not in all_texts


def test_story_card_has_no_duplicate_seasons():
    kb = story_card(story_id=42)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "▶️ Прохождение" in all_texts
    assert "📚 Сезоны" not in all_texts
    # Verify callbacks
    all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert all_cbs.count("seasons:42") == 1


def test_guide_keyboard_has_no_filter_buttons():
    kb = guide_filters(episode_id=1, season_id=10)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    # Filter buttons must be completely absent
    assert not any("Все" in t for t in all_texts)
    assert not any("Параметры" in t for t in all_texts)
    assert not any("Романтика" in t for t in all_texts)
    assert not any("Критичные" in t for t in all_texts)
    # Diamond savings must also be completely absent
    assert not any("Экономия алмазов" in t for t in all_texts)
    # Navigation must be present
    assert any("🔙 Серии" in t for t in all_texts)
    assert any("🏠 Меню" in t for t in all_texts)


def test_settings_keyboard_simplified_without_spoilers():
    # Enabled
    kb_on = _settings_keyboard(notifications_enabled=True)
    texts_on = [btn.text for row in kb_on.inline_keyboard for btn in row]
    assert "🔕 Отключить уведомления" in texts_on
    assert not any("спойлер" in t.lower() for t in texts_on)
    assert "🏠 Меню" in texts_on

    # Disabled
    kb_off = _settings_keyboard(notifications_enabled=False)
    texts_off = [btn.text for row in kb_off.inline_keyboard for btn in row]
    assert "🔔 Включить уведомления" in texts_off
    assert not any("спойлер" in t.lower() for t in texts_off)


def test_character_text_formatting():
    story = Story(id=40, title="Секрет Небес")
    char = Character(
        id=1,
        story_id=40,
        name="Люцифер",
        description="Сын Сатаны, будущий владыка Ада.",
        status="Демон",
        is_love_interest=True,
        facts="Один из сильнейших демонов.",
        story=story,
    )
    formatted = character_text(char)
    assert "👤 Люцифер" in formatted
    assert "Сын Сатаны" in formatted
    assert "Статус: Демон" in formatted
    assert "❤️ Романтическая ветка: Да" in formatted
    assert "📖 История: Секрет Небес" in formatted
    assert "💡 Факты и особенности:\nОдин из сильнейших демонов." in formatted
    assert "спойлер" not in formatted.lower()


def test_database_characters_populated():
    con = sqlite3.connect("club_romance.db")
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM characters;")
    total_chars = cur.fetchone()[0]
    assert total_chars >= 50, f"Expected >= 50 characters, found {total_chars}"

    # Verify love interests
    cur.execute("SELECT count(*) FROM characters WHERE is_love_interest = 1;")
    love_interests = cur.fetchone()[0]
    assert love_interests >= 30, f"Expected >= 30 love interests, found {love_interests}"

    # Check key characters exist
    cur.execute("SELECT name FROM characters WHERE name IN ('Люцифер', 'Амен', 'Кадзу', 'Виктор Ван Арт');")
    found_names = [r[0] for r in cur.fetchall()]
    assert "Люцифер" in found_names
    assert "Амен" in found_names
    assert "Кадзу" in found_names
    assert "Виктор Ван Арт" in found_names

    con.close()


def test_classify_choice_badges():
    from bot.utils.formatting import classify_choice

    # 1. Negative relationship (💔)
    c_neg = Choice(text="Нагрубить", consequence="Ухудшение отношений с Аменом")
    assert classify_choice(c_neg)[0] == "💔"

    # 2. Positive relationship (❤️)
    c_pos = Choice(text="Поцеловать его", consequence="+1 отношения с Люцифером")
    assert classify_choice(c_pos)[0] == "❤️"

    # 3. Stat loss (🔻)
    c_loss = Choice(text="Ошибиться на балу", consequence="Минус 1 Слава")
    assert classify_choice(c_loss)[0] == "🔻"

    # 4. Critical plot choice (🟡)
    c_plot = Choice(text="Спрятать улику", consequence="Повлияет на сюжет в будущем", is_critical=True)
    assert classify_choice(c_plot)[0] == "🟡"

    # 5. Reputation / Fame (🟢)
    c_rep = Choice(text="Ответить с достоинством", consequence="+1 Слава")
    assert classify_choice(c_rep)[0] == "🟢"

    # 6. Alt / Mystical stat (🟣)
    c_mystic = Choice(text="Взглянуть в зеркало", consequence="+1 Морок")
    assert classify_choice(c_mystic)[0] == "🟣"

    # 7. Main stat (🔹)
    c_main = Choice(text="Подумать логически", consequence="+1 Логика")
    assert classify_choice(c_main)[0] == "🔹"

    # 8. Diamond paid choice without special tags (💎)
    c_diam = Choice(text="Купить красивое платье", cost_diamonds=30)
    assert classify_choice(c_diam)[0] == "💎"

    # 9. Neutral choice (▫️)
    c_neutral = Choice(text="Пойти спать")
    assert classify_choice(c_neutral)[0] == "▫️"


def test_format_choice_item_renders_badge_and_bold():
    from bot.utils.formatting import format_choice_item

    c = Choice(
        text="Поцеловать Кадзу",
        cost_diamonds=25,
        consequence="Улучшение отношений",
        parameter_changes='["+1 Ниндзюцу"]',
    )
    formatted = format_choice_item(c)
    # Checks that it starts with ❤️ badge (ignoring leading indentation)
    assert formatted.strip().startswith("❤️ ")
    # Checks that choice text is bolded
    assert "<b>Поцеловать Кадзу</b>" in formatted
    # Checks that cost is rendered
    assert "💎 25 алмазов" in formatted
    # Checks that parameter change is rendered
    assert "+1 Ниндзюцу" in formatted
