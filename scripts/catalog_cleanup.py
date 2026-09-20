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


def run_catalog_cleanup(db_path: Path = Path("club_romance.db")) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Database {db_path} not found")

    pre_size = db_path.stat().st_size
    pre_sha = compute_sha256(db_path)

    # 1. Create and verify backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(f"club_romance_before_phase15_catalog_cleanup_{timestamp}.db")
    shutil.copy2(db_path, backup_path)

    backup_size = backup_path.stat().st_size
    backup_sha = compute_sha256(backup_path)
    assert backup_size == pre_size, "Backup size mismatch"
    assert backup_sha == pre_sha, "Backup hash mismatch"

    # Verify backup integrity
    bcon = sqlite3.connect(backup_path)
    bcur = bcon.cursor()
    bcur.execute("PRAGMA integrity_check")
    b_integ = bcur.fetchone()[0]
    bcon.close()
    assert b_integ == "ok", f"Backup integrity check failed: {b_integ}"

    print(f"[OK] Backup created: {backup_path}")
    print(f"     Size: {backup_size} bytes | SHA-256: {backup_sha}")

    # 2. Execute cleanup in a single transaction
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    try:
        cur.execute("BEGIN TRANSACTION")

        # Story Title updates
        story_updates = [
            (85, "Te Amo. Том 2: Хрустальная мечта", "te-amo-tom-2-khrustalnaya-mechta", "Te Amo. Том 1: Залив надежды"),
            (60, "Te Amo. Том 1: Залив надежды", "te-amo-tom-1", "Te Amo"),
            (49, "Эдемов сад", "edemov-sad", "Райский сад"),
            (54, "И поглотит нас морок", "i-poglotit-nas-morok", "И туман поглотит нас"),
            (56, "Шифр Шекспира", "shifr-shekspira", "Код Шекспира"),
            (59, "Пришествие Номер Три", "prishestvie-nomer-tri", "Адвент №3"),
            (61, "Код синий", "kod-siniy", "Код Блю"),
        ]

        updated_stories = []
        for sid, new_title, new_slug, old_expected in story_updates:
            cur.execute("SELECT title, slug FROM stories WHERE id = ?", (sid,))
            row = cur.fetchone()
            assert row is not None, f"Story {sid} not found"
            old_title, old_slug = row
            cur.execute("UPDATE stories SET title = ?, slug = ? WHERE id = ?", (new_title, new_slug, sid))
            updated_stories.append({"id": sid, "old_title": old_title, "new_title": new_title, "old_slug": old_slug, "new_slug": new_slug})

        # Season Title cleanups
        cur.execute("SELECT id, story_id, number, title FROM seasons ORDER BY id")
        all_seasons = cur.fetchall()

        cleaned_seasons = []
        for s_id, st_id, s_num, s_title in all_seasons:
            raw = (s_title or "").strip()
            if raw in (f"Сезон {s_num}", "Первое расследование"):
                continue

            is_verbose = (
                "прохождение" in raw.lower()
                or raw.startswith("Аверрис:")
                or raw.startswith("Грехи,")
                or raw.startswith("Тени Сентфора 2.")
                or raw.startswith("Водяная Лилия.")
                or raw.startswith("Рождённая Солнцем.")
                or raw.startswith("Рождённый Тенью.")
                or raw.startswith("О красном и безмолвном море.")
            )

            if is_verbose:
                m_tom = re.search(r"Том\s*(\d+)", raw, re.IGNORECASE)
                if m_tom:
                    new_stitle = f"Том {m_tom.group(1)}"
                elif "спец" in raw.lower():
                    new_stitle = "Специальный выпуск"
                else:
                    new_stitle = f"Сезон {s_num}"

                if new_stitle != raw:
                    cur.execute("UPDATE seasons SET title = ? WHERE id = ?", (new_stitle, s_id))
                    cleaned_seasons.append({"id": s_id, "story_id": st_id, "number": s_num, "old_title": raw, "new_title": new_stitle})

        cur.execute("COMMIT")
        print(f"[OK] Transaction committed: {len(updated_stories)} stories renamed, {len(cleaned_seasons)} season titles cleaned.")

    except Exception as e:
        cur.execute("ROLLBACK")
        con.close()
        raise RuntimeError(f"Cleanup failed, rolled back: {e}")

    # 3. Post-cleanup verification
    cur.execute("PRAGMA integrity_check")
    post_integ = cur.fetchone()[0]

    cur.execute("PRAGMA foreign_key_check")
    fk_violations = len(cur.fetchall())

    cur.execute("SELECT count(*) FROM stories")
    stories_cnt = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM seasons")
    seasons_cnt = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM episodes")
    episodes_cnt = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM choices")
    choices_cnt = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM progress")
    progress_cnt = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM subscriptions")
    subscriptions_cnt = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM characters")
    characters_cnt = cur.fetchone()[0]

    con.close()

    assert post_integ == "ok", f"Integrity check failed: {post_integ}"
    assert fk_violations == 0, f"Foreign key check failed: {fk_violations} violations"
    assert stories_cnt == 64, f"Stories count changed: {stories_cnt} != 64"
    assert seasons_cnt == 150, f"Seasons count changed: {seasons_cnt} != 150"
    assert episodes_cnt == 1671, f"Episodes count changed: {episodes_cnt} != 1671"
    assert choices_cnt == 55351, f"Choices count changed: {choices_cnt} != 55351"
    assert progress_cnt == 6, f"Progress count changed: {progress_cnt} != 6"
    assert subscriptions_cnt == 1, f"Subscriptions count changed: {subscriptions_cnt} != 1"
    assert characters_cnt == 2, f"Characters count changed: {characters_cnt} != 2"

    post_size = db_path.stat().st_size
    post_sha = compute_sha256(db_path)

    print(f"[OK] Verification passed completely!")
    print(f"     Stories: {stories_cnt}, Seasons: {seasons_cnt}, Episodes: {episodes_cnt}, Choices: {choices_cnt}")
    print(f"     User data intact: progress={progress_cnt}, subs={subscriptions_cnt}, chars={characters_cnt}")
    print(f"     Integrity: {post_integ}, FK violations: {fk_violations}")
    print(f"     New DB Size: {post_size} bytes | New SHA-256: {post_sha}")

    return {
        "backup_path": str(backup_path),
        "backup_sha": backup_sha,
        "backup_size": backup_size,
        "updated_stories": updated_stories,
        "cleaned_seasons": cleaned_seasons,
        "post_sha": post_sha,
        "post_size": post_size,
    }


if __name__ == "__main__":
    res = run_catalog_cleanup()
    print("\nSummary of Renamed Stories:")
    for s in res["updated_stories"]:
        print(f"   ID {s['id']:2d}: '{s['old_title']}' -> '{s['new_title']}' (slug: '{s['new_slug']}')")
    print(f"\nTotal Cleaned Season Titles: {len(res['cleaned_seasons'])}")
