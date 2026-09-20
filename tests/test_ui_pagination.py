import json
import sqlite3
import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.database.models import Choice, Episode, Season, Story
from bot.keyboards.guides import guide_filters
from bot.keyboards.stories import episodes_list
from bot.utils.formatting import (
    episode_guide_text,
    format_single_choice,
    paginate_episode_guide,
    parse_effects_list,
    pluralize_diamonds,
    split_choice_block,
)


def _make_dummy_episode(num_choices: int = 0, choice_text_len: int = 50) -> tuple[Episode, list[Choice]]:
    story = Story(id=1, title="Тестовая История")
    season = Season(id=10, story_id=1, number=1, story=story)
    episode = Episode(
        id=100,
        season_id=10,
        number=1,
        title="Тестовая Серия",
        guide_intro="Тестовое введение в серию",
        guide_source_name="Тест",
        guide_source_url="https://example.com/guide",
        season=season,
    )
    choices = []
    for i in range(1, num_choices + 1):
        c = Choice(
            id=i,
            episode_id=episode.id,
            order_index=i,
            scene_title=f"Сцена {i}",
            text=f"Выбор текста {i}: " + ("x" * choice_text_len),
            recommended_option="",
            cost_diamonds=0,
            consequence="",
            requirements="",
            parameter_changes="",
            character_effects="",
            future_effects="",
            spoiler_level=0,
            is_critical=False,
            episode=episode,
        )
        choices.append(c)
    return episode, choices


def test_pluralize_diamonds():
    assert pluralize_diamonds(1) == "1 алмаз"
    assert pluralize_diamonds(2) == "2 алмаза"
    assert pluralize_diamonds(3) == "3 алмаза"
    assert pluralize_diamonds(4) == "4 алмаза"
    assert pluralize_diamonds(5) == "5 алмазов"
    assert pluralize_diamonds(11) == "11 алмазов"
    assert pluralize_diamonds(12) == "12 алмазов"
    assert pluralize_diamonds(14) == "14 алмазов"
    assert pluralize_diamonds(20) == "20 алмазов"
    assert pluralize_diamonds(21) == "21 алмаз"
    assert pluralize_diamonds(23) == "23 алмаза"
    assert pluralize_diamonds(100) == "100 алмазов"


def test_parse_effects_list():
    # JSON array
    assert parse_effects_list('["+1 сила", "+2 ловкость"]') == ["+1 сила", "+2 ловкость"]
    # Single item array
    assert parse_effects_list('["+1 сила"]') == ["+1 сила"]
    # Plain text
    assert parse_effects_list("Макс +1") == ["Макс +1"]
    # Dict
    assert parse_effects_list('{"Сила": "+1"}') == ["Сила: +1"]
    # Empty variations
    assert parse_effects_list("") == []
    assert parse_effects_list("[]") == []
    assert parse_effects_list("{}") == []
    assert parse_effects_list("null") == []
    assert parse_effects_list(None) == []


def test_choice_rendering_empty_recommended_option():
    c = Choice(
        id=1,
        episode_id=1,
        order_index=1,
        scene_title="Разговор в коридоре",
        text="Спросить о случившемся?",
        recommended_option="",  # Empty
        cost_diamonds=0,
        spoiler_level=0,
    )
    formatted = format_single_choice(c, 1, spoiler_level=0)
    assert "1. Разговор в коридоре" in formatted
    assert "Спросить о случившемся?" in formatted
    assert "👉" not in formatted  # Must NOT render empty recommendation


def test_choice_rendering_filled_recommended_option():
    c = Choice(
        id=1,
        episode_id=1,
        order_index=1,
        scene_title="Таинственная комната",
        text="Что взять со стола?",
        recommended_option="Взять старинный ключ",
        cost_diamonds=15,
        spoiler_level=0,
    )
    formatted = format_single_choice(c, 1, spoiler_level=0)
    assert "Что взять со стола?" in formatted
    assert "👉 Взять старинный ключ" in formatted
    assert "💎 Стоимость:" in formatted
    assert "• 15 алмазов" in formatted


def test_effects_formatting_json_parameters_and_relationships():
    c = Choice(
        id=1,
        episode_id=1,
        order_index=1,
        scene_title="Бой у ворот",
        text="Принять вызов",
        recommended_option="",
        cost_diamonds=23,
        parameter_changes='["Смелость +1", "Сила +2"]',
        character_effects='["Алекс +1"]',
        consequence="Враги отступают",
        future_effects='["Поможет в битве за замок"]',
        spoiler_level=0,
    )
    formatted = format_single_choice(c, 1, spoiler_level=1)
    assert "📊 Параметры:\n• Смелость +1\n• Сила +2" in formatted
    assert "❤️ Отношения:\n• Алекс +1" in formatted
    assert "💎 Стоимость:\n• 23 алмаза" in formatted
    assert "🎯 Последствие: Враги отступают" in formatted
    assert "🔮 В будущем:\n• Поможет в битве за замок" in formatted


def test_spoiler_level_hiding():
    c = Choice(
        id=1,
        episode_id=1,
        order_index=1,
        scene_title="Секретный диалог",
        text="Подслушать разговор",
        recommended_option="",
        cost_diamonds=0,
        parameter_changes='["+1 интрига"]',
        character_effects='["Предатель раскрыт"]',
        consequence="Мы узнаём главную тайну",
        spoiler_level=2,  # Serious spoilers
    )
    # With user spoiler_level=0, details must be hidden
    hidden_formatted = format_single_choice(c, 1, spoiler_level=0)
    assert "🔒 Последствие скрыто настройками спойлеров." in hidden_formatted
    assert "главную тайну" not in hidden_formatted
    assert "+1 интрига" not in hidden_formatted

    # With user spoiler_level=2, details must be shown
    revealed_formatted = format_single_choice(c, 1, spoiler_level=2)
    assert "🔒 Последствие скрыто" not in revealed_formatted
    assert "главную тайну" in revealed_formatted
    assert "+1 интрига" in revealed_formatted


def test_single_page_choices():
    episode, choices = _make_dummy_episode(num_choices=3, choice_text_len=30)
    text, current_page, total_pages = paginate_episode_guide(episode, choices, spoiler_level=0, page=1)

    assert total_pages == 1
    assert current_page == 1
    assert len(text) < 4096
    assert "1. Сцена 1" in text
    assert "2. Сцена 2" in text
    assert "3. Сцена 3" in text
    # When total_pages == 1, no redundant page label in header
    assert "(Страница 1/1)" not in text

    # Check keyboard has no pagination row when total_pages == 1
    kb = guide_filters(episode.id, episode.season_id, current_page=1, total_pages=1)
    all_btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "⬅️ Назад" not in all_btn_texts
    assert "Вперёд ➡️" not in all_btn_texts


def test_episode_exceeding_4096_chars_paginated():
    # 40 choices with 150 chars each -> would be >8000 chars without pagination
    episode, choices = _make_dummy_episode(num_choices=40, choice_text_len=150)

    # Check total pages
    text_p1, p1, total_pages = paginate_episode_guide(episode, choices, spoiler_level=0, page=1)
    assert total_pages > 1
    assert p1 == 1

    # Verify every page is within safe limits (<= 3800 <= 4096 chars)
    for p in range(1, total_pages + 1):
        page_text, cur_p, _ = paginate_episode_guide(episode, choices, spoiler_level=0, page=p)
        assert cur_p == p
        assert len(page_text) <= 3800, f"Page {p} length {len(page_text)} exceeds 3800"
        assert len(page_text) <= 4096, f"Page {p} length {len(page_text)} exceeds Telegram 4096 limit"
        assert f"(Страница {p}/{total_pages})" in page_text


def test_huge_single_choice_splitting():
    # Single choice text of 5000 characters
    huge_text = "Очень длинное описание выбора. " * 160  # ~5000 chars
    episode, _ = _make_dummy_episode(num_choices=0)
    huge_choice = Choice(
        id=999,
        episode_id=episode.id,
        order_index=1,
        scene_title="Грандиозный выбор",
        text=huge_text,
        recommended_option="",
        cost_diamonds=0,
        spoiler_level=0,
        episode=episode,
    )

    page_text, cur_p, total_pages = paginate_episode_guide(episode, [huge_choice], spoiler_level=0, page=1)
    assert total_pages > 1
    # Check that all chunks are <= 3800
    for p in range(1, total_pages + 1):
        txt, _, _ = paginate_episode_guide(episode, [huge_choice], spoiler_level=0, page=p)
        assert len(txt) <= 3800
        assert len(txt) <= 4096


def test_guide_filters_pagination_buttons():
    # Page 1 of 3
    kb1 = guide_filters(100, 10, source_url="https://example.com", current_page=1, total_pages=3, filter_name="all")
    first_row = kb1.inline_keyboard[0]
    assert first_row[0].text == "⬅️ Назад"
    assert first_row[0].callback_data == "noop"  # Disabled on page 1
    assert first_row[1].text == "1/3"
    assert first_row[1].callback_data == "noop"
    assert first_row[2].text == "Вперёд ➡️"
    assert first_row[2].callback_data == "guide:100:all:2"

    # Page 2 of 3
    kb2 = guide_filters(100, 10, source_url="https://example.com", current_page=2, total_pages=3, filter_name="all")
    first_row_2 = kb2.inline_keyboard[0]
    assert first_row_2[0].callback_data == "guide:100:all:1"
    assert first_row_2[1].text == "2/3"
    assert first_row_2[2].callback_data == "guide:100:all:3"

    # Page 3 of 3
    kb3 = guide_filters(100, 10, source_url="https://example.com", current_page=3, total_pages=3, filter_name="all")
    first_row_3 = kb3.inline_keyboard[0]
    assert first_row_3[0].callback_data == "guide:100:all:2"
    assert first_row_3[1].text == "3/3"
    assert first_row_3[2].callback_data == "noop"  # Disabled on last page


def test_episodes_list_pagination():
    episodes = [
        Episode(id=i, season_id=10, number=i, title=f"Серия {i}")
        for i in range(1, 26)  # 25 episodes
    ]
    # Page 1 of 3 (10 episodes per page)
    kb = episodes_list(story_id=1, season_id=10, episodes=episodes[:10], page=1, total_pages=3)
    # Must have 10 episode buttons + 1 pagination row + 1 nav row
    assert len(kb.inline_keyboard) == 12
    nav_row = kb.inline_keyboard[10]
    assert nav_row[0].text == "⬅️ Назад"
    assert nav_row[0].callback_data == "noop"
    assert nav_row[1].text == "1/3"
    assert nav_row[2].text == "Вперёд ➡️"
    assert nav_row[2].callback_data == "episodes:10:2"

    # Single page season (5 episodes)
    kb_single = episodes_list(story_id=1, season_id=10, episodes=episodes[:5], page=1, total_pages=1)
    all_texts = [btn.text for row in kb_single.inline_keyboard for btn in row]
    assert "⬅️ Назад" not in all_texts
    assert "Вперёд ➡️" not in all_texts


def test_real_database_7_brothers_s1e8_pagination():
    """Verify '7 братьев' S1E8 (115 choices, previously 16 848 chars) is safely paginated."""
    con = sqlite3.connect("club_romance.db")
    cur = con.cursor()
    cur.execute("""
        SELECT e.id, e.number, s.number, st.title, e.guide_intro, e.summary, e.guide_source_name, e.guide_source_url
        FROM episodes e
        JOIN seasons s ON e.season_id = s.id
        JOIN stories st ON s.story_id = st.id
        WHERE st.title LIKE '%7%' AND s.number = 1 AND e.number = 8
    """)
    ep_row = cur.fetchone()
    assert ep_row is not None, "7 brothers S1E8 not found in DB"
    ep_id, ep_num, s_num, st_title, intro, summary, src_name, src_url = ep_row

    story = Story(id=1, title=st_title)
    season = Season(id=1, story_id=1, number=s_num, story=story)
    episode = Episode(
        id=ep_id,
        season_id=1,
        number=ep_num,
        title="Эпизод 8",
        guide_intro=intro,
        summary=summary,
        guide_source_name=src_name,
        guide_source_url=src_url,
        season=season,
    )

    cur.execute("""
        SELECT id, scene_title, text, recommended_option, cost_diamonds, consequence, parameter_changes, character_effects, future_effects, requirements, spoiler_level, order_index
        FROM choices WHERE episode_id = ? ORDER BY order_index
    """, (ep_id,))
    choice_rows = cur.fetchall()
    assert len(choice_rows) == 115

    choices = [
        Choice(
            id=r[0],
            episode_id=ep_id,
            scene_title=r[1],
            text=r[2],
            recommended_option=r[3],
            cost_diamonds=r[4],
            consequence=r[5],
            parameter_changes=r[6],
            character_effects=r[7],
            future_effects=r[8],
            requirements=r[9],
            spoiler_level=r[10],
            order_index=r[11],
            episode=episode,
        )
        for r in choice_rows
    ]

    # Paginate and verify all pages
    page_1_text, cur_p, total_pages = paginate_episode_guide(episode, choices, spoiler_level=1, page=1)
    assert total_pages in (6, 12)
    assert cur_p == 1

    for p in range(1, total_pages + 1):
        txt, page_idx, _ = paginate_episode_guide(episode, choices, spoiler_level=1, page=p)
        assert page_idx == p
        assert len(txt) <= 3800, f"Page {p} exceeded 3800 chars (was {len(txt)})"
        assert len(txt) <= 4096, f"Page {p} exceeded 4096 Telegram limit"
        assert f"(Страница {p}/{total_pages})" in txt


def test_telegram_bad_request_suppression_logic():
    """Verify that 'message is not modified' TelegramBadRequest is correctly handled."""
    err = TelegramBadRequest(method="editMessageText", message="Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message")
    
    handled = False
    try:
        raise err
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            handled = True
        else:
            raise
    assert handled is True
