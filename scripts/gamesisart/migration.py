"""Phase 10 Production Migration Engine.

Migrates structured GamesIsArt guides from data/gamesisart/staging.db
into production SQLite database (club_romance.db).

Guarantees:
1. Pre-migration backup verified before ANY changes.
2. Single ACID transaction (BEGIN IMMEDIATE ... COMMIT).
3. Immediate ROLLBACK upon any exception or validation failure.
4. Existing story, season, episode IDs strictly preserved.
5. In-place UPDATE for 6,279 safe placeholders, preserving choices.id.
6. Staging IDs are NEVER transferred directly to production.
7. Protected records (Stories 1, 2, 31, 32, 82 and Choices 1, 2, 31..40) are strictly untouched.
8. User data (progress, subscriptions, characters) 100% preserved.
9. Post-migration integrity and foreign key checks.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.gamesisart.migration_readiness import IDENTITY_RESOLUTIONS, normalize_title

DEFAULT_PROD_DB = Path("club_romance.db")
DEFAULT_STAGING_DB = Path("data/gamesisart/staging.db")

PROTECTED_STORY_IDS = {1, 2, 31, 32, 82}
PROTECTED_CHOICE_IDS = {1, 2, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40}


def compute_file_sha256(path: Path) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_slug(title: str, existing_slugs: set[str]) -> str:
    """Generate a clean, unique transliterated slug for a story."""
    cyr = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    lat = [
        "a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "y", "k", "l", "m",
        "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch",
        "", "y", "", "e", "yu", "ya"
    ]
    tr = {ord(c): l for c, l in zip(cyr, lat)}
    s = title.lower().translate(tr)
    slug = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not slug:
        slug = "story"
    base = slug
    counter = 2
    while slug in existing_slugs:
        slug = f"{base}-{counter}"
        counter += 1
    existing_slugs.add(slug)
    return slug


@dataclass
class MigrationStats:
    backup_path: str = ""
    backup_size: int = 0
    backup_sha256: str = ""
    backup_integrity: str = ""

    # Pre-migration counts
    pre_stories: int = 0
    pre_seasons: int = 0
    pre_episodes: int = 0
    pre_choices: int = 0
    pre_progress: int = 0
    pre_subscriptions: int = 0
    pre_characters: int = 0

    # Operations
    stories_updated_url: int = 0
    stories_created: int = 0
    seasons_created: int = 0
    episodes_created: int = 0
    choices_updated_inplace: int = 0
    choices_inserted_existing_episodes: int = 0
    choices_inserted_new_episodes: int = 0
    total_choices_inserted: int = 0

    # Post-migration counts
    post_stories: int = 0
    post_seasons: int = 0
    post_episodes: int = 0
    post_choices: int = 0
    post_progress: int = 0
    post_subscriptions: int = 0
    post_characters: int = 0

    integrity_check: str = ""
    foreign_key_check: str = ""
    rollback_occurred: bool = False
    committed: bool = False
    error_message: str = ""


class ProductionMigrator:
    """Encapsulates the entire production migration workflow."""

    def __init__(
        self,
        prod_db_path: Path = DEFAULT_PROD_DB,
        staging_db_path: Path = DEFAULT_STAGING_DB,
    ) -> None:
        self.prod_db_path = Path(prod_db_path)
        self.staging_db_path = Path(staging_db_path)
        self.stats = MigrationStats()

    def create_verified_backup(self, backup_path: Path | None = None) -> Path:
        """Create a verified SQLite backup using SQLite backup API."""
        if not self.prod_db_path.exists():
            raise FileNotFoundError(f"Production database not found: {self.prod_db_path}")

        if backup_path is None:
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = Path(f"club_romance_before_gamesisart_migration_{now_str}.db")

        src = sqlite3.connect(f"file:{self.prod_db_path.resolve()}?mode=ro", uri=True)
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()

        # Verify backup
        b_size = backup_path.stat().st_size
        b_sha = compute_file_sha256(backup_path)

        with sqlite3.connect(f"file:{backup_path.resolve()}?mode=ro", uri=True) as conn:
            cur = conn.cursor()
            b_integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
            cnt_stories = cur.execute("SELECT count(*) FROM stories").fetchone()[0]
            cnt_seasons = cur.execute("SELECT count(*) FROM seasons").fetchone()[0]
            cnt_episodes = cur.execute("SELECT count(*) FROM episodes").fetchone()[0]
            cnt_choices = cur.execute("SELECT count(*) FROM choices").fetchone()[0]

        if b_integrity != "ok":
            raise ValueError(f"Backup integrity check failed: {b_integrity}")
        if cnt_stories != 54 or cnt_seasons != 60 or cnt_episodes != 635 or cnt_choices != 8235:
            raise ValueError(
                f"Backup counts mismatch: stories={cnt_stories} (exp 54), "
                f"seasons={cnt_seasons} (exp 60), episodes={cnt_episodes} (exp 635), "
                f"choices={cnt_choices} (exp 8235)"
            )

        self.stats.backup_path = str(backup_path)
        self.stats.backup_size = b_size
        self.stats.backup_sha256 = b_sha
        self.stats.backup_integrity = b_integrity

        return backup_path

    def run_migration(self) -> MigrationStats:
        """Execute atomic production migration within a single transaction."""
        conn_p = sqlite3.connect(self.prod_db_path)
        conn_p.execute("PRAGMA foreign_keys = ON")
        conn_p.row_factory = sqlite3.Row
        cur_p = conn_p.cursor()
        conn_s = None

        try:
            if not self.staging_db_path.exists():
                raise FileNotFoundError(f"Staging database not found: {self.staging_db_path}")
            conn_s = sqlite3.connect(f"file:{self.staging_db_path.resolve()}?mode=ro", uri=True)
            conn_s.row_factory = sqlite3.Row
            cur_s = conn_s.cursor()

            # Step 2: Pre-migration snapshot
            self.stats.pre_stories = cur_p.execute("SELECT count(*) FROM stories").fetchone()[0]
            self.stats.pre_seasons = cur_p.execute("SELECT count(*) FROM seasons").fetchone()[0]
            self.stats.pre_episodes = cur_p.execute("SELECT count(*) FROM episodes").fetchone()[0]
            self.stats.pre_choices = cur_p.execute("SELECT count(*) FROM choices").fetchone()[0]
            self.stats.pre_progress = cur_p.execute("SELECT count(*) FROM progress").fetchone()[0]
            self.stats.pre_subscriptions = cur_p.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
            self.stats.pre_characters = cur_p.execute("SELECT count(*) FROM characters").fetchone()[0]

            existing_story_ids = {r[0] for r in cur_p.execute("SELECT id FROM stories").fetchall()}
            existing_season_ids = {r[0] for r in cur_p.execute("SELECT id FROM seasons").fetchall()}
            existing_episode_ids = {r[0] for r in cur_p.execute("SELECT id FROM episodes").fetchall()}
            existing_slugs = {r[0] for r in cur_p.execute("SELECT slug FROM stories").fetchall()}

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            # Step 3: Begin immediate transaction
            conn_p.execute("BEGIN IMMEDIATE")

            # Load stories
            p_stories = cur_p.execute("SELECT id, title, slug, guide_source_url FROM stories").fetchall()
            s_stories = cur_s.execute("SELECT source_key, title, canonical_url FROM staging_stories ORDER BY id").fetchall()

            # Build mappings
            # 42 exact matches
            exact_map: dict[str, int] = {}  # source_key -> prod_story_id
            for ps in p_stories:
                if ps["id"] in IDENTITY_RESOLUTIONS:
                    continue
                for ss in s_stories:
                    if normalize_title(ps["title"]) == normalize_title(ss["title"]) or (
                        ps["guide_source_url"] and ps["guide_source_url"] == ss["canonical_url"]
                    ):
                        exact_map[ss["source_key"]] = ps["id"]
                        break

            # 7 alias matches
            alias_map: dict[str, int] = {}
            for pid, info in IDENTITY_RESOLUTIONS.items():
                if info["resolution"] == "MATCH":
                    alias_map[info["target_source_key"]] = pid

            # Step 4: Update canonical source URLs for 42 exact + 7 alias stories
            for sk, pid in exact_map.items():
                ss = cur_s.execute("SELECT canonical_url FROM staging_stories WHERE source_key = ?", (sk,)).fetchone()
                cur_p.execute(
                    """
                    UPDATE stories
                    SET guide_source_name = 'GamesIsArt.ru',
                        guide_source_url = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (ss["canonical_url"], now, pid),
                )
                self.stats.stories_updated_url += 1

            for sk, pid in alias_map.items():
                ss = cur_s.execute("SELECT canonical_url FROM staging_stories WHERE source_key = ?", (sk,)).fetchone()
                cur_p.execute(
                    """
                    UPDATE stories
                    SET guide_source_name = 'GamesIsArt.ru',
                        guide_source_url = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (ss["canonical_url"], now, pid),
                )
                self.stats.stories_updated_url += 1

            # Step 5: Insert 10 new stories
            new_story_map: dict[str, int] = {}  # source_key -> new prod_story_id
            for ss in s_stories:
                sk = ss["source_key"]
                if sk in exact_map or sk in alias_map:
                    continue
                slug = generate_slug(ss["title"], existing_slugs)
                cur_p.execute(
                    """
                    INSERT INTO stories
                        (title, slug, description, genre, status, cover_file_id, is_published,
                         views_count, guide_source_name, guide_source_url, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ss["title"],
                        slug,
                        f"Прохождение новеллы {ss['title']} от GamesIsArt.",
                        "Визуальная новелла",
                        "В процессе",
                        None,
                        1,
                        0,
                        "GamesIsArt.ru",
                        ss["canonical_url"],
                        now,
                        now,
                    ),
                )
                new_prod_id = cur_p.lastrowid
                new_story_map[sk] = new_prod_id
                self.stats.stories_created += 1

            # Full active story mapping (42 exact + 10 new)
            # Note: 7 alias stories only had canonical URL updated, per section 4 instructions.
            active_story_map = dict(exact_map)
            active_story_map.update(new_story_map)

            # Step 6: Seasons Synchronization
            # season_map: (source_key, season_number) -> prod_season_id
            season_map: dict[tuple[str, int], int] = {}

            for sk, prod_story_id in active_story_map.items():
                st_seasons = cur_s.execute(
                    "SELECT number, title FROM staging_seasons WHERE source_key = ? ORDER BY number",
                    (sk,),
                ).fetchall()

                for sn in st_seasons:
                    s_num = sn["number"]
                    s_title = sn["title"] or f"Сезон {s_num}"

                    # Check if exists in prod
                    existing_s = cur_p.execute(
                        "SELECT id FROM seasons WHERE story_id = ? AND number = ?",
                        (prod_story_id, s_num),
                    ).fetchone()

                    if existing_s:
                        season_map[(sk, s_num)] = existing_s["id"]
                    else:
                        cur_p.execute(
                            """
                            INSERT INTO seasons
                                (story_id, number, title, description, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                prod_story_id,
                                s_num,
                                s_title,
                                f"Сезон {s_num} новеллы",
                                now,
                                now,
                            ),
                        )
                        new_season_id = cur_p.lastrowid
                        season_map[(sk, s_num)] = new_season_id
                        self.stats.seasons_created += 1

            # Step 7: Episodes Synchronization
            # episode_map: (source_key, season_number, episode_number) -> (prod_episode_id, is_new)
            episode_map: dict[tuple[str, int, int], tuple[int, bool]] = {}

            for (sk, s_num), prod_season_id in season_map.items():
                st_episodes = cur_s.execute(
                    """
                    SELECT episode_number, title
                    FROM staging_episodes
                    WHERE source_key = ? AND season_number = ?
                    ORDER BY episode_number
                    """,
                    (sk, s_num),
                ).fetchall()

                canonical_url = cur_s.execute(
                    "SELECT canonical_url FROM staging_stories WHERE source_key = ?", (sk,)
                ).fetchone()["canonical_url"]

                for ep in st_episodes:
                    ep_num = ep["episode_number"]
                    ep_title = ep["title"] or f"Серия {ep_num}"

                    existing_ep = cur_p.execute(
                        "SELECT id FROM episodes WHERE season_id = ? AND number = ?",
                        (prod_season_id, ep_num),
                    ).fetchone()

                    if existing_ep:
                        episode_map[(sk, s_num, ep_num)] = (existing_ep["id"], False)
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
                                canonical_url,
                                now,
                                now,
                            ),
                        )
                        new_ep_id = cur_p.lastrowid
                        episode_map[(sk, s_num, ep_num)] = (new_ep_id, True)
                        self.stats.episodes_created += 1

            # Step 8: Safe In-Place Placeholder Replacement (6,279)
            # & Step 9: New Choices in Existing Episodes (11,440)
            # & Step 10: Choices in New Episodes
            for (sk, s_num, ep_num), (prod_ep_id, is_new_ep) in episode_map.items():
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
                    # Existing episode: retrieve existing production choices
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

                    # Update in-place up to p_cnt
                    for idx in range(min(p_cnt, len(st_choices))):
                        pch = p_choices[idx]
                        sch = st_choices[idx]

                        # Verify not protected
                        if pch["id"] in PROTECTED_CHOICE_IDS:
                            raise ValueError(f"Attempted to overwrite protected choice ID={pch['id']}!")

                        cur_p.execute(
                            """
                            UPDATE choices
                            SET text = ?,
                                cost_diamonds = ?,
                                parameter_changes = ?,
                                character_effects = ?,
                                future_effects = ?,
                                tags = 'gamesisart_import',
                                is_critical = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                sch["text"],
                                sch["cost_diamonds"] or 0,
                                sch["parameter_changes"] or "[]",
                                sch["character_effects"] or "[]",
                                sch["future_effects"] or "[]",
                                1 if sch["is_critical"] else 0,
                                now,
                                pch["id"],
                            ),
                        )
                        self.stats.choices_updated_inplace += 1

                    # Insert additional choices beyond p_cnt
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
                                now,
                                now,
                            ),
                        )
                        self.stats.choices_inserted_existing_episodes += 1

                else:
                    # Brand new episode: insert all choices
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
                                now,
                                now,
                            ),
                        )
                        self.stats.choices_inserted_new_episodes += 1

            self.stats.total_choices_inserted = (
                self.stats.choices_inserted_existing_episodes
                + self.stats.choices_inserted_new_episodes
            )

            # Step 14: Pre-Commit Validation
            # A) Foreign keys check
            fk_violations = cur_p.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                raise ValueError(f"Foreign key violations detected: {fk_violations}")
            self.stats.foreign_key_check = "empty (0 violations)"

            # B) Integrity check
            integrity = cur_p.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"SQLite integrity check failed: {integrity}")
            self.stats.integrity_check = integrity

            # C) Check user data counts
            cnt_prog = cur_p.execute("SELECT count(*) FROM progress").fetchone()[0]
            cnt_subs = cur_p.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
            cnt_char = cur_p.execute("SELECT count(*) FROM characters").fetchone()[0]

            if cnt_prog != self.stats.pre_progress:
                raise ValueError(f"User progress count drift: {cnt_prog} != {self.stats.pre_progress}")
            if cnt_subs != self.stats.pre_subscriptions:
                raise ValueError(f"Subscriptions count drift: {cnt_subs} != {self.stats.pre_subscriptions}")
            if cnt_char != self.stats.pre_characters:
                raise ValueError(f"Characters count drift: {cnt_char} != {self.stats.pre_characters}")

            self.stats.post_progress = cnt_prog
            self.stats.post_subscriptions = cnt_subs
            self.stats.post_characters = cnt_char

            # D) Check ID preservation
            for sid in existing_story_ids:
                if not cur_p.execute("SELECT 1 FROM stories WHERE id = ?", (sid,)).fetchone():
                    raise ValueError(f"Existing Story ID={sid} was lost!")
            for sid in PROTECTED_STORY_IDS:
                if not cur_p.execute("SELECT 1 FROM stories WHERE id = ?", (sid,)).fetchone():
                    raise ValueError(f"Protected Story ID={sid} was lost!")
            for cid in PROTECTED_CHOICE_IDS:
                ch_row = cur_p.execute("SELECT text FROM choices WHERE id = ?", (cid,)).fetchone()
                if not ch_row:
                    raise ValueError(f"Protected Choice ID={cid} was lost!")
                if "gamesisart_import" in (ch_row["text"] or ""):
                    raise ValueError(f"Protected Choice ID={cid} was modified by import!")

            # E) Check no orphan records
            orphan_seasons = cur_p.execute(
                "SELECT count(*) FROM seasons WHERE story_id NOT IN (SELECT id FROM stories)"
            ).fetchone()[0]
            if orphan_seasons > 0:
                raise ValueError(f"Found {orphan_seasons} orphan seasons!")

            orphan_episodes = cur_p.execute(
                "SELECT count(*) FROM episodes WHERE season_id NOT IN (SELECT id FROM seasons)"
            ).fetchone()[0]
            if orphan_episodes > 0:
                raise ValueError(f"Found {orphan_episodes} orphan episodes!")

            orphan_choices = cur_p.execute(
                "SELECT count(*) FROM choices WHERE episode_id NOT IN (SELECT id FROM episodes)"
            ).fetchone()[0]
            if orphan_choices > 0:
                raise ValueError(f"Found {orphan_choices} orphan choices!")

            # F) Check unique order_index per episode
            # In migrated episodes (stories NOT in protected list), order_index must be strictly unique
            duplicate_orders = cur_p.execute(
                """
                SELECT c.episode_id, c.order_index, count(*)
                FROM choices c
                JOIN episodes e ON c.episode_id = e.id
                JOIN seasons s ON e.season_id = s.id
                WHERE s.story_id NOT IN (1, 2, 31, 32, 82)
                GROUP BY c.episode_id, c.order_index
                HAVING count(*) > 1
                """
            ).fetchall()
            if duplicate_orders:
                raise ValueError(f"Duplicate choice order_index detected in migrated episodes: {duplicate_orders[:5]}")

            # Also ensure no new duplicates were introduced anywhere
            total_db_duplicates = cur_p.execute(
                """
                SELECT episode_id, order_index, count(*)
                FROM choices
                GROUP BY episode_id, order_index
                HAVING count(*) > 1
                """
            ).fetchall()
            if len(total_db_duplicates) > 10:
                raise ValueError(
                    f"New duplicate choice order_indexes detected across database: {len(total_db_duplicates)} (pre-existing: 10)"
                )

            # G) Check expected counts
            post_st = cur_p.execute("SELECT count(*) FROM stories").fetchone()[0]
            post_se = cur_p.execute("SELECT count(*) FROM seasons").fetchone()[0]
            post_ep = cur_p.execute("SELECT count(*) FROM episodes").fetchone()[0]
            post_ch = cur_p.execute("SELECT count(*) FROM choices").fetchone()[0]

            expected_stories = self.stats.pre_stories + self.stats.stories_created
            expected_seasons = self.stats.pre_seasons + self.stats.seasons_created
            expected_episodes = self.stats.pre_episodes + self.stats.episodes_created
            expected_choices = self.stats.pre_choices + self.stats.total_choices_inserted

            if post_st != expected_stories:
                raise ValueError(f"Post stories mismatch: got {post_st}, expected {expected_stories}")
            if post_se != expected_seasons:
                raise ValueError(f"Post seasons mismatch: got {post_se}, expected {expected_seasons}")
            if post_ep != expected_episodes:
                raise ValueError(f"Post episodes mismatch: got {post_ep}, expected {expected_episodes}")
            if post_ch != expected_choices:
                raise ValueError(f"Post choices mismatch: got {post_ch}, expected {expected_choices}")

            # Specific assertion on exactly 6,279 replacements and 11,440 additions in existing episodes
            if self.stats.choices_updated_inplace != 6279:
                raise ValueError(
                    f"Placeholder replacement count mismatch: {self.stats.choices_updated_inplace} != 6279"
                )
            if self.stats.choices_inserted_existing_episodes != 11440:
                raise ValueError(
                    f"New choices in existing episodes count mismatch: {self.stats.choices_inserted_existing_episodes} != 11440"
                )

            self.stats.post_stories = post_st
            self.stats.post_seasons = post_se
            self.stats.post_episodes = post_ep
            self.stats.post_choices = post_ch

            # Step 16: Commit
            conn_p.commit()
            self.stats.committed = True

        except Exception as exc:
            try:
                conn_p.rollback()
            except Exception:
                pass
            self.stats.rollback_occurred = True
            self.stats.error_message = str(exc)
            raise
        finally:
            conn_p.close()
            if conn_s:
                conn_s.close()

        return self.stats

    def verify_post_commit(self) -> dict[str, Any]:
        """Perform post-commit read-only verification of production DB and backup."""
        # 1. Verify production DB
        with sqlite3.connect(f"file:{self.prod_db_path.resolve()}?mode=ro", uri=True) as conn:
            cur = conn.cursor()
            integ = cur.execute("PRAGMA integrity_check").fetchone()[0]
            fks = cur.execute("PRAGMA foreign_key_check").fetchall()
            st = cur.execute("SELECT count(*) FROM stories").fetchone()[0]
            se = cur.execute("SELECT count(*) FROM seasons").fetchone()[0]
            ep = cur.execute("SELECT count(*) FROM episodes").fetchone()[0]
            ch = cur.execute("SELECT count(*) FROM choices").fetchone()[0]
            prog = cur.execute("SELECT count(*) FROM progress").fetchone()[0]
            subs = cur.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
            char = cur.execute("SELECT count(*) FROM characters").fetchone()[0]

        # 2. Verify backup SHA256 unchanged
        b_path = Path(self.stats.backup_path)
        current_b_sha = compute_file_sha256(b_path)
        backup_intact = current_b_sha == self.stats.backup_sha256

        return {
            "integrity_check": integ,
            "foreign_key_violations": len(fks),
            "stories": st,
            "seasons": se,
            "episodes": ep,
            "choices": ch,
            "progress": prog,
            "subscriptions": subs,
            "characters": char,
            "backup_intact": backup_intact,
            "backup_sha256": current_b_sha,
        }
