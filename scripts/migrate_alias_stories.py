"""Targeted migration script for the 7 alias stories in club_romance.db.

Syncs all missing seasons, episodes, and choices from data/gamesisart/staging.db
for the 7 alias stories (IDs: 47, 49, 54, 56, 59, 60, 61).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")
from scripts.gamesisart.migration_readiness import IDENTITY_RESOLUTIONS
from scripts.clean_all_episode_titles import run_clean_titles

PROD_DB = Path("club_romance.db")
STAGING_DB = Path("data/gamesisart/staging.db")


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_alias_migration() -> None:
    print("=" * 60)
    print("MIGRATING 7 ALIAS STORIES TO PRODUCTION")
    print("=" * 60)

    if not PROD_DB.exists():
        raise FileNotFoundError(f"Prod DB not found: {PROD_DB}")
    if not STAGING_DB.exists():
        raise FileNotFoundError(f"Staging DB not found: {STAGING_DB}")

    # 1. Backup
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = Path(f"club_romance_before_alias_migration_{now_str}.db")
    print(f"\n[1] Creating verified backup: {backup_file.name}...")
    src = sqlite3.connect(f"file:{PROD_DB.resolve()}?mode=ro", uri=True)
    dst = sqlite3.connect(backup_file)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()

    with sqlite3.connect(f"file:{backup_file.resolve()}?mode=ro", uri=True) as conn_b:
        integ = conn_b.execute("PRAGMA integrity_check").fetchone()[0]
        if integ != "ok":
            raise ValueError(f"Backup integrity check failed: {integ}")
    print(f"  Backup OK: {backup_file.stat().st_size} bytes (SHA256: {compute_file_sha256(backup_file)})")

    # 2. Migration in transaction
    conn_p = sqlite3.connect(PROD_DB)
    conn_p.execute("PRAGMA foreign_keys = ON")
    conn_p.row_factory = sqlite3.Row
    cur_p = conn_p.cursor()

    conn_s = sqlite3.connect(f"file:{STAGING_DB.resolve()}?mode=ro", uri=True)
    conn_s.row_factory = sqlite3.Row
    cur_s = conn_s.cursor()

    # Pre-snapshot
    pre_stories = cur_p.execute("SELECT count(*) FROM stories").fetchone()[0]
    pre_seasons = cur_p.execute("SELECT count(*) FROM seasons").fetchone()[0]
    pre_episodes = cur_p.execute("SELECT count(*) FROM episodes").fetchone()[0]
    pre_choices = cur_p.execute("SELECT count(*) FROM choices").fetchone()[0]
    pre_progress = cur_p.execute("SELECT count(*) FROM progress").fetchone()[0]
    pre_subscriptions = cur_p.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
    pre_characters = cur_p.execute("SELECT count(*) FROM characters").fetchone()[0]

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    alias_map: dict[str, int] = {}
    for pid, info in IDENTITY_RESOLUTIONS.items():
        if info["resolution"] == "MATCH":
            alias_map[info["target_source_key"]] = pid

    print(f"\n[2] Executing migration for {len(alias_map)} stories: {alias_map}...")
    cur_p.execute("BEGIN IMMEDIATE")

    seasons_created = 0
    episodes_created = 0
    choices_updated_inplace = 0
    choices_inserted_existing_episodes = 0
    choices_inserted_new_episodes = 0

    try:
        for sk, prod_story_id in alias_map.items():
            # A. Update canonical URL
            st_story = cur_s.execute(
                "SELECT canonical_url FROM staging_stories WHERE source_key = ?", (sk,)
            ).fetchone()
            cur_p.execute(
                """
                UPDATE stories
                SET guide_source_name = 'GamesIsArt.ru',
                    guide_source_url = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (st_story["canonical_url"], now_utc, prod_story_id),
            )

            # B. Seasons
            st_seasons = cur_s.execute(
                "SELECT number, title FROM staging_seasons WHERE source_key = ? ORDER BY number",
                (sk,),
            ).fetchall()

            season_map: dict[int, int] = {}  # season_number -> prod_season_id
            for sn in st_seasons:
                s_num = sn["number"]
                s_title = sn["title"] or f"Сезон {s_num}"
                existing_s = cur_p.execute(
                    "SELECT id FROM seasons WHERE story_id = ? AND number = ?",
                    (prod_story_id, s_num),
                ).fetchone()

                if existing_s:
                    season_map[s_num] = existing_s["id"]
                else:
                    cur_p.execute(
                        """
                        INSERT INTO seasons
                            (story_id, number, title, description, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (prod_story_id, s_num, s_title, f"Сезон {s_num} новеллы", now_utc, now_utc),
                    )
                    season_map[s_num] = cur_p.lastrowid
                    seasons_created += 1

            # C. Episodes & Choices
            for s_num, prod_season_id in season_map.items():
                st_episodes = cur_s.execute(
                    """
                    SELECT episode_number, title
                    FROM staging_episodes
                    WHERE source_key = ? AND season_number = ?
                    ORDER BY episode_number
                    """,
                    (sk, s_num),
                ).fetchall()

                for ep in st_episodes:
                    ep_num = ep["episode_number"]
                    ep_title = ep["title"] or f"Серия {ep_num}"

                    existing_ep = cur_p.execute(
                        "SELECT id FROM episodes WHERE season_id = ? AND number = ?",
                        (prod_season_id, ep_num),
                    ).fetchone()

                    is_new_ep = False
                    if existing_ep:
                        prod_ep_id = existing_ep["id"]
                    else:
                        cur_p.execute(
                            """
                            INSERT INTO episodes
                                (season_id, number, title, summary, guide_intro, image_file_id,
                                 is_published, guide_source_name, guide_source_url, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                prod_season_id,
                                ep_num,
                                ep_title,
                                "",
                                "",
                                None,
                                1,
                                "GamesIsArt.ru",
                                st_story["canonical_url"],
                                now_utc,
                                now_utc,
                            ),
                        )
                        prod_ep_id = cur_p.lastrowid
                        episodes_created += 1
                        is_new_ep = True

                    # Staging choices for this episode
                    st_choices = cur_s.execute(
                        """
                        SELECT order_index, text, cost_diamonds, parameter_changes,
                               character_effects, future_effects, is_critical, tags
                        FROM staging_choices
                        WHERE source_key = ? AND season_number = ? AND episode_number = ?
                        ORDER BY order_index
                        """,
                        (sk, s_num, ep_num),
                    ).fetchall()

                    if not is_new_ep:
                        p_choices = cur_p.execute(
                            """
                            SELECT id, order_index, text, tags, recommended_option, scene_title
                            FROM choices
                            WHERE episode_id = ?
                            ORDER BY order_index
                            """,
                            (prod_ep_id,),
                        ).fetchall()
                        p_cnt = len(p_choices)

                        # Update in-place
                        for idx in range(min(p_cnt, len(st_choices))):
                            pch = p_choices[idx]
                            sch = st_choices[idx]
                            cur_p.execute(
                                """
                                UPDATE choices
                                SET order_index = ?,
                                    text = ?,
                                    cost_diamonds = ?,
                                    parameter_changes = ?,
                                    character_effects = ?,
                                    future_effects = ?,
                                    is_critical = ?,
                                    tags = 'gamesisart_import',
                                    updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    sch["order_index"],
                                    sch["text"],
                                    sch["cost_diamonds"] or 0,
                                    sch["parameter_changes"] or "[]",
                                    sch["character_effects"] or "[]",
                                    sch["future_effects"] or "[]",
                                    1 if sch["is_critical"] else 0,
                                    now_utc,
                                    pch["id"],
                                ),
                            )
                            choices_updated_inplace += 1

                        # Insert choices beyond p_cnt
                        for idx in range(p_cnt, len(st_choices)):
                            sch = st_choices[idx]
                            cur_p.execute(
                                """
                                INSERT INTO choices
                                    (episode_id, order_index, scene_title, text, recommended_option,
                                     cost_diamonds, consequence, requirements, parameter_changes,
                                     character_effects, future_effects, tags, spoiler_level,
                                     is_critical, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    prod_ep_id,
                                    sch["order_index"],
                                    None,
                                    sch["text"],
                                    "",
                                    sch["cost_diamonds"] or 0,
                                    "",
                                    "",
                                    sch["parameter_changes"] or "[]",
                                    sch["character_effects"] or "[]",
                                    sch["future_effects"] or "[]",
                                    "gamesisart_import",
                                    0,
                                    1 if sch["is_critical"] else 0,
                                    now_utc,
                                    now_utc,
                                ),
                            )
                            choices_inserted_existing_episodes += 1
                    else:
                        # New episode: insert all choices
                        for sch in st_choices:
                            cur_p.execute(
                                """
                                INSERT INTO choices
                                    (episode_id, order_index, scene_title, text, recommended_option,
                                     cost_diamonds, consequence, requirements, parameter_changes,
                                     character_effects, future_effects, tags, spoiler_level,
                                     is_critical, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    prod_ep_id,
                                    sch["order_index"],
                                    None,
                                    sch["text"],
                                    "",
                                    sch["cost_diamonds"] or 0,
                                    "",
                                    "",
                                    sch["parameter_changes"] or "[]",
                                    sch["character_effects"] or "[]",
                                    sch["future_effects"] or "[]",
                                    "gamesisart_import",
                                    0,
                                    1 if sch["is_critical"] else 0,
                                    now_utc,
                                    now_utc,
                                ),
                            )
                            choices_inserted_new_episodes += 1

        # Post-validation inside transaction
        post_integ = cur_p.execute("PRAGMA integrity_check").fetchone()[0]
        if post_integ != "ok":
            raise ValueError(f"Integrity check failed: {post_integ}")
        fk_violations = cur_p.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise ValueError(f"Foreign key violations: {fk_violations}")

        post_prog = cur_p.execute("SELECT count(*) FROM progress").fetchone()[0]
        post_subs = cur_p.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
        post_char = cur_p.execute("SELECT count(*) FROM characters").fetchone()[0]
        if post_prog != pre_progress or post_subs != pre_subscriptions or post_char != pre_characters:
            raise ValueError("User data altered during migration!")

        conn_p.commit()
        print("  Transaction committed successfully!")

    except Exception as e:
        conn_p.rollback()
        print(f"  Migration failed and rolled back: {e}")
        raise
    finally:
        conn_p.close()
        conn_s.close()

    print(f"\n[3] Migration Stats:")
    print(f"  Seasons created: {seasons_created}")
    print(f"  Episodes created: {episodes_created}")
    print(f"  Choices updated in-place: {choices_updated_inplace}")
    print(f"  Choices inserted in existing episodes: {choices_inserted_existing_episodes}")
    print(f"  Choices inserted in new episodes: {choices_inserted_new_episodes}")
    print(f"  Total choices added: {choices_inserted_existing_episodes + choices_inserted_new_episodes}")

    # 4. Clean episode titles
    print("\n[4] Running clean episode titles...")
    run_clean_titles(PROD_DB)
    print("  Episode titles cleaned successfully!")


if __name__ == "__main__":
    run_alias_migration()
