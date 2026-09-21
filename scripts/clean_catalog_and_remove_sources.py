"""
Safe atomic script to clean episode titles and remove all mentions of GamesIsArt.

1. Creates verified backup.
2. Cleans corrupted/glued episode titles:
   - S1 E2-E10 of "7 братьев": strips 'Семь братьев...' SEO tails.
   - Cleans glued tails across all stories (gamesisart.ru, Romance Club, Прохождение, 1 сезон N серия, etc.).
3. Removes all occurrences of 'GamesIsArt' across:
   - stories.description
   - stories.guide_source_name, stories.guide_source_url
   - seasons.description
   - episodes.title (e.g. '...gamesisart.ru')
   - episodes.summary ('Серия импортирована с GamesIsArt.ru.')
   - episodes.guide_source_name, episodes.guide_source_url
   - choices.tags (replaces 'gamesisart_import' with 'guide')
4. Verifies database integrity and zero FK violations.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


CLEAN_TITLE_PATTERNS = [
    # 7 brothers specific glued subtitles
    re.compile(r"Семь братьев\..*$", re.IGNORECASE),
    re.compile(r"Клуб романтики\.\s*Семь братьев.*$", re.IGNORECASE),
    # General SEO glued patterns at end of episode title
    re.compile(r"gamesisart\.ru.*$", re.IGNORECASE),
    re.compile(r"Клуб романтики\.\s*gamesisart.*$", re.IGNORECASE),
    re.compile(r"Romance Club\..*$", re.IGNORECASE),
    re.compile(r"В ритме страсти\..*$", re.IGNORECASE),
    re.compile(r"Разбитое сердце Астреи\..*$", re.IGNORECASE),
    re.compile(r"Секрет Небес.*gamesisart.*$", re.IGNORECASE),
    re.compile(r"Рожденная луной\..*$", re.IGNORECASE),
    re.compile(r"Королева за 30 дней\..*$", re.IGNORECASE),
    re.compile(r"Клуб романтики\.\s*За 30 дней\..*$", re.IGNORECASE),
    re.compile(r"Я Охочусь на Тебя.*$", re.IGNORECASE),
    re.compile(r"ЯОНТ\..*$", re.IGNORECASE),
]


def clean_episode_title(title: str) -> str:
    cleaned = title.strip()
    for pat in CLEAN_TITLE_PATTERNS:
        cleaned = pat.sub("", cleaned).strip()
    # Clean trailing punctuation leftover
    cleaned = re.sub(r"[\s\.\,\-]+$", "", cleaned).strip()
    return cleaned or title.strip()


def run_cleanup(db_path: Path = Path("club_romance.db")) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Database {db_path} not found.")

    pre_size = db_path.stat().st_size
    pre_sha = compute_sha256(db_path)

    # Backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"club_romance_before_clean_titles_{ts}.db"
    shutil.copy2(db_path, backup_path)
    assert backup_path.stat().st_size == pre_size
    assert compute_sha256(backup_path) == pre_sha

    bcon = sqlite3.connect(backup_path)
    bcur = bcon.cursor()
    bcur.execute("PRAGMA integrity_check;")
    assert bcur.fetchone()[0] == "ok"
    bcon.close()
    print(f"[OK] Backup verified: {backup_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("BEGIN TRANSACTION;")

        # 1. Clean episode titles
        cur.execute("SELECT id, title FROM episodes;")
        all_eps = cur.fetchall()
        cleaned_eps_count = 0
        for ep_id, ep_title in all_eps:
            if not ep_title:
                continue
            new_title = clean_episode_title(ep_title)
            if new_title != ep_title:
                cur.execute("UPDATE episodes SET title = ? WHERE id = ?;", (new_title, ep_id))
                cleaned_eps_count += 1

        print(f"[OK] Cleaned {cleaned_eps_count} episode titles.")

        # 2. Clean stories descriptions and sources
        cur.execute("""
            UPDATE stories
            SET description = ''
            WHERE description LIKE '%GamesIsArt%';
        """)
        cleaned_stories_desc = cur.rowcount

        cur.execute("""
            UPDATE stories
            SET guide_source_name = NULL,
                guide_source_url = NULL;
        """)

        # 3. Clean seasons descriptions
        cur.execute("""
            UPDATE seasons
            SET description = ''
            WHERE description LIKE '%GamesIsArt%';
        """)
        cleaned_seasons_desc = cur.rowcount

        # 4. Clean episodes summaries and sources
        cur.execute("""
            UPDATE episodes
            SET summary = ''
            WHERE summary LIKE '%GamesIsArt%';
        """)
        cleaned_eps_summary = cur.rowcount

        cur.execute("""
            UPDATE episodes
            SET guide_source_name = NULL,
                guide_source_url = NULL;
        """)

        # 5. Clean choices tags (replace gamesisart_import with guide)
        cur.execute("""
            UPDATE choices
            SET tags = REPLACE(tags, 'gamesisart_import', 'guide')
            WHERE tags LIKE '%gamesisart_import%';
        """)
        cleaned_tags = cur.rowcount

        cur.execute("COMMIT;")
        print(f"[OK] Removed GamesIsArt: {cleaned_stories_desc} story descs, {cleaned_seasons_desc} season descs, {cleaned_eps_summary} episode summaries, {cleaned_tags} choice tags.")

    except Exception as e:
        cur.execute("ROLLBACK;")
        conn.close()
        raise RuntimeError(f"Cleanup failed, rolled back: {e}")

    # Post-verification
    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"
    cur.execute("PRAGMA foreign_key_check;")
    assert len(cur.fetchall()) == 0

    # Verify no gamesisart in visible user text fields
    cur.execute("SELECT count(*) FROM stories WHERE description LIKE '%gamesisart%';")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM episodes WHERE title LIKE '%gamesisart%' OR summary LIKE '%gamesisart%';")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM seasons WHERE description LIKE '%gamesisart%';")
    assert cur.fetchone()[0] == 0

    conn.close()

    post_size = db_path.stat().st_size
    post_sha = compute_sha256(db_path)
    print(f"[OK] Post-cleanup check passed! Size={post_size} bytes | SHA-256={post_sha}")

    return {
        "backup_path": str(backup_path),
        "cleaned_eps_count": cleaned_eps_count,
        "post_sha": post_sha,
    }


if __name__ == "__main__":
    run_cleanup()
