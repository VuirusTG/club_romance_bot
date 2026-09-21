"""
Safe script to clean all remaining episode titles in club_romance.db.
Strips glued SEO tails and website branding from episode titles.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def build_story_pattern(st_title: str) -> list[str]:
    variants = [st_title]
    clean_title = re.sub(r"^[A-Za-z]:\s*", "", st_title)
    if clean_title != st_title:
        variants.append(clean_title)
    abbrs = {
        "Кали: Пламя Сансары": ["Кали 2", "КПС", "Кали: Пламя Сансары"],
        "Эдемов сад": ["ЭС", "Эдемов сад"],
        "Бездушная": ["БД", "Бездушная"],
        "Разбитое сердце Астреи": ["РСА", "Разбитое сердце Астреи"],
        "Секрет Небес": ["СН", "Секрет Небес"],
        "Секрет Небес 2": ["СН2", "СН 2", "КР СН", "Секрет Небес 2"],
        "Секрет Небес: Реквием": ["СН3", "СН 3", "Секрет Небес 3: Реквием", "Секрет Небес 3", "Секрет Небес: Реквием"],
        "Любовь, Грех и Зло": ["ЛГиЗ", "Любовь, Грех и Зло"],
        "W: Ловчая времени": ["Ловчая Времени", "Ловчая времени", "ЛВ"],
        "И поглотит нас морок": ["ИПНМ", "И поглотит нас морок"],
        "Сага о грозах": ["СоГ", "Сага о грозах"],
        "Шифр Шекспира": ["ШШ", "Шифр Шекспира"],
        "Я Охочусь на Тебя": ["ЯОНТ", "Яонт", "Я Охочусь на Тебя"],
        "Я Охочусь на Тебя 2": ["ЯОнТ 2", "ЯОНТ 2", "Я Охочусь на Тебя 2"],
        "Рождённая Луной": ["Рожденная Луной", "Рожденная луной", "Рождённая луной", "КР. Рождённая луной"],
        "7 братьев": ["Семь братьев", "7 братьев"],
        "Королева за 30 дней": ["За 30 дней", "Королева за 30 дней"],
    }
    if st_title in abbrs:
        variants.extend(abbrs[st_title])
    return list(dict.fromkeys(variants))


GENERIC_SUFFIX_REGEX = re.compile(
    r"(?:"
    r"Клуб\s+романтики.*|"
    r"Romance\s+Club.*|"
    r"gamesisart.*|"
    r"Прохождение.*|"
    r"Гайд.*|"
    r"Что\s+(?:выбрать|это|значит|отвечать).*|"
    r"Где\s+(?:взять|скачать|накопить).*|"
    r"Все\s+(?:варианты|ответы|диалоги).*|"
    r"Платные\s+ответы.*|"
    r"Как\s+отвечать.*|"
    r"\d+\s+сезон.*|"
    r"Сезон\s+\d+.*|"
    r"Том\s+\d+.*"
    r")$",
    re.IGNORECASE,
)


def run_clean_titles(db_path: Path = Path("club_romance.db")) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT e.id, st.title, e.title 
        FROM episodes e 
        JOIN seasons s ON e.season_id = s.id 
        JOIN stories st ON s.story_id = st.id;
    """)
    rows = cur.fetchall()

    updates = []
    for ep_id, st_title, title in rows:
        if not title:
            continue
        cleaned = title

        variants = build_story_pattern(st_title)
        for v in sorted(variants, key=len, reverse=True):
            esc_v = re.escape(v)
            cleaned = re.sub(rf"[\s\.\,\-\—\–\(]*{esc_v}.*$", "", cleaned, flags=re.IGNORECASE)

        cleaned = GENERIC_SUFFIX_REGEX.sub("", cleaned)
        cleaned = re.sub(r"[\s\.\,\-\—\–\:\;]+$", "", cleaned).strip()

        if cleaned and cleaned != title:
            updates.append((cleaned, ep_id))

    if updates:
        cur.executemany("UPDATE episodes SET title = ? WHERE id = ?;", updates)
        conn.commit()

    # Integrity verification
    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"
    cur.execute("PRAGMA foreign_key_check;")
    assert len(cur.fetchall()) == 0

    conn.close()
    print(f"[OK] Cleaned {len(updates)} episode titles in {db_path}.")
    return len(updates)


if __name__ == "__main__":
    run_clean_titles()
