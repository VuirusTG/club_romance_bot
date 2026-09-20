"""
Safe Atomic Structural Deduplication & Catalog Cleanup Script.

Handles:
  - Merging duplicate stories:
      * Story 77 (canonical) vs Story 83 (duplicate) -> delete 83
      * Story 57 (canonical) vs Story 84 (duplicate) -> delete 84
      * Story 32 (canonical, 5 seasons) vs Story 31 (incomplete duplicate, 1 season) -> delete 31, update slug of 32
  - Cleaning up test stubs:
      * Story 2 ('Тест') -> delete
      * Story 82 ('Тест 3') -> delete
      * Story 1 ('Тени Сентфора', test mock) -> clean test progress/subs/chars and delete
  - Normalizing 'Идеал' (ID 77) seasons to 'Том 1' and 'Том 2'
  - Verifying integrity and zero FK violations
"""
from __future__ import annotations

import hashlib
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


def deduplicate_catalog(db_path: Path = Path("club_romance.db"), create_backup: bool = True) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Database {db_path} does not exist.")

    pre_size = db_path.stat().st_size
    pre_sha = compute_sha256(db_path)

    backup_path = None
    backup_sha = None
    backup_size = None

    if create_backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.parent / f"club_romance_before_phase16_dedup_{ts}.db"
        shutil.copy2(db_path, backup_path)
        backup_size = backup_path.stat().st_size
        backup_sha = compute_sha256(backup_path)
        assert backup_size == pre_size, "Backup size mismatch"
        assert backup_sha == pre_sha, "Backup SHA-256 mismatch"

        bcon = sqlite3.connect(backup_path)
        bcur = bcon.cursor()
        bcur.execute("PRAGMA integrity_check;")
        res = bcur.fetchone()[0]
        bcon.close()
        assert res == "ok", f"Backup integrity check failed: {res}"
        print(f"[OK] Backup created and verified: {backup_path} ({backup_size} bytes)")

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    try:
        cur.execute("BEGIN TRANSACTION;")

        # Enable foreign keys for checking, but perform controlled cascade
        cur.execute("PRAGMA foreign_keys = OFF;")

        # 1. Check existing stories
        cur.execute("SELECT id, title, slug FROM stories;")
        all_stories = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        to_delete = [sid for sid in [1, 2, 31, 82, 83, 84] if sid in all_stories]
        print(f"[INFO] Stories to remove/merge: {to_delete}")

        # 2. Merge user references if any exist
        merge_map = {
            83: 77,  # Ideal
            84: 57,  # Bureau
            31: 32,  # Moonborn
        }

        for dup_id, canon_id in merge_map.items():
            if dup_id in all_stories:
                # Progress
                cur.execute("UPDATE OR IGNORE progress SET story_id = ? WHERE story_id = ?;", (canon_id, dup_id))
                cur.execute("DELETE FROM progress WHERE story_id = ?;", (dup_id,))
                # Subscriptions
                cur.execute("UPDATE OR IGNORE subscriptions SET story_id = ? WHERE story_id = ?;", (canon_id, dup_id))
                cur.execute("DELETE FROM subscriptions WHERE story_id = ?;", (dup_id,))
                # Favorites
                cur.execute("UPDATE OR IGNORE favorites SET item_id = ? WHERE item_type = 'story' AND item_id = ?;", (canon_id, dup_id))
                cur.execute("DELETE FROM favorites WHERE item_type = 'story' AND item_id = ?;", (dup_id,))

        # 3. Clean up deleted stories and their children
        for sid in to_delete:
            # Delete choices
            cur.execute("""
                DELETE FROM choices WHERE episode_id IN (
                    SELECT e.id FROM episodes e
                    JOIN seasons s ON e.season_id = s.id
                    WHERE s.story_id = ?
                );
            """, (sid,))
            # Delete episodes
            cur.execute("""
                DELETE FROM episodes WHERE season_id IN (
                    SELECT id FROM seasons WHERE story_id = ?
                );
            """, (sid,))
            # Delete seasons
            cur.execute("DELETE FROM seasons WHERE story_id = ?;", (sid,))
            # Delete parameters, characters, romance_routes
            cur.execute("DELETE FROM parameters WHERE story_id = ?;", (sid,))
            cur.execute("DELETE FROM characters WHERE story_id = ?;", (sid,))
            cur.execute("DELETE FROM romance_routes WHERE story_id = ?;", (sid,))
            # Delete any remaining progress/subs/favorites for stubs (1, 2, 82)
            cur.execute("DELETE FROM progress WHERE story_id = ?;", (sid,))
            cur.execute("DELETE FROM subscriptions WHERE story_id = ?;", (sid,))
            cur.execute("DELETE FROM favorites WHERE item_type = 'story' AND item_id = ?;", (sid,))
            # Delete story
            cur.execute("DELETE FROM stories WHERE id = ?;", (sid,))

        # 4. Canonical updates
        # Story 32 slug check
        if 32 in all_stories or (cur.execute("SELECT id FROM stories WHERE id = 32;").fetchone() is not None):
            cur.execute("UPDATE stories SET slug = 'rozhdennaya-lunoi' WHERE id = 32;")

        # Story 77 seasons normalize to "Том 1" and "Том 2"
        cur.execute("SELECT id, number, title FROM seasons WHERE story_id = 77 ORDER BY number;")
        s77_rows = cur.fetchall()
        for s_id, s_num, s_title in s77_rows:
            target_title = f"Том {s_num}"
            if s_title != target_title:
                cur.execute("UPDATE seasons SET title = ? WHERE id = ?;", (target_title, s_id))

        cur.execute("COMMIT;")
        print("[OK] Transaction committed successfully.")

    except Exception as e:
        cur.execute("ROLLBACK;")
        con.close()
        raise RuntimeError(f"Deduplication failed, rolled back: {e}")

    # Verification
    cur.execute("PRAGMA integrity_check;")
    integ = cur.fetchone()[0]
    assert integ == "ok", f"Integrity check failed: {integ}"

    cur.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    assert len(fk_errors) == 0, f"Foreign key violations found: {fk_errors}"

    cur.execute("SELECT count(*) FROM stories;")
    total_stories = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM seasons;")
    total_seasons = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM episodes;")
    total_episodes = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM choices;")
    total_choices = cur.fetchone()[0]

    con.close()

    post_size = db_path.stat().st_size
    post_sha = compute_sha256(db_path)

    print(f"[OK] Verification complete: Stories={total_stories}, Seasons={total_seasons}, Episodes={total_episodes}, Choices={total_choices}")
    print(f"     DB Size: {post_size} bytes | SHA-256: {post_sha}")

    return {
        "backup_path": str(backup_path) if backup_path else None,
        "backup_sha": backup_sha,
        "post_sha": post_sha,
        "stories": total_stories,
        "seasons": total_seasons,
        "episodes": total_episodes,
        "choices": total_choices,
    }


if __name__ == "__main__":
    deduplicate_catalog()
