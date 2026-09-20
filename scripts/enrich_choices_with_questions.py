"""
Safe Atomic Script to enrich club_romance.db with real questions and clean choice options
from parsed GamesIsArt JSON data.

1. Creates verified pre-update backup.
2. Clears redundant intro boilerplate from episodes.
3. Associates each choice with its true scene question (scene_title).
4. Sets clean option text with consequences/characteristics.
5. Clears placeholder consequence and recommended_option artifacts.
6. Verifies database integrity and zero FK violations.
"""
from __future__ import annotations

import hashlib
import json
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


def enrich_choices_and_episodes(
    db_path: Path = Path("club_romance.db"),
    parsed_dir: Path = Path("data/gamesisart/parsed"),
) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Database {db_path} not found.")

    pre_size = db_path.stat().st_size
    pre_sha = compute_sha256(db_path)

    # 1. Create and verify backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"club_romance_before_guide_enrich_{ts}.db"
    shutil.copy2(db_path, backup_path)
    assert backup_path.stat().st_size == pre_size
    assert compute_sha256(backup_path) == pre_sha

    bcon = sqlite3.connect(backup_path)
    bcur = bcon.cursor()
    bcur.execute("PRAGMA integrity_check;")
    assert bcur.fetchone()[0] == "ok"
    bcon.close()
    print(f"[OK] Backup created and verified: {backup_path}")

    # 2. Update database in a single transaction
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("BEGIN TRANSACTION;")

        # A. Clear boilerplate intro from all episodes
        cur.execute("""
            UPDATE episodes
            SET guide_intro = ''
            WHERE guide_intro LIKE '%Гайд автоматически собран%'
               OR guide_intro LIKE '%Серия импортирована%';
        """)
        cleared_intros = cur.rowcount
        print(f"[OK] Cleared boilerplate guide_intro from {cleared_intros} episodes.")

        # B. Clean old placeholder texts in choices
        cur.execute("""
            UPDATE choices
            SET consequence = ''
            WHERE consequence LIKE 'Краткий импортированный пункт:%';
        """)
        cleared_conseq = cur.rowcount

        cur.execute("""
            UPDATE choices
            SET scene_title = NULL
            WHERE scene_title LIKE 'Пункт гайда%';
        """)
        cleared_scenes = cur.rowcount

        cur.execute("""
            UPDATE choices
            SET recommended_option = ''
            WHERE recommended_option LIKE 'См. краткое последствие'
               OR recommended_option LIKE '%Выборы, которые влияют%';
        """)
        cleared_recs = cur.rowcount
        print(f"[OK] Cleaned placeholders: {cleared_conseq} consequences, {cleared_scenes} scene titles, {cleared_recs} recommendations.")

        # C. Match parsed JSON and enrich choices with Questions (scene_title) and full text
        cur.execute("SELECT id, title, guide_source_url FROM stories ORDER BY id;")
        stories = cur.fetchall()

        enriched_episodes = 0
        enriched_choices = 0

        for sid, stitle, surl in stories:
            if not surl:
                continue
            stem = Path(surl).stem.lower()
            candidates = list(parsed_dir.glob(f"*{stem}*.json"))
            if not candidates:
                short_stem = stem.replace("romance_club_", "")
                candidates = list(parsed_dir.glob(f"*{short_stem}*.json"))
            if not candidates:
                continue

            with open(candidates[0], "r", encoding="utf-8") as f:
                doc = json.load(f)

            doc_seasons = {s["number"]: s for s in doc.get("seasons", [])}

            cur.execute("SELECT id, number FROM seasons WHERE story_id = ? ORDER BY number;", (sid,))
            db_seasons = cur.fetchall()

            for season_id, s_num in db_seasons:
                doc_season = doc_seasons.get(s_num)
                if not doc_season:
                    continue

                doc_episodes = {ep["number"]: ep for ep in doc_season.get("episodes", [])}
                cur.execute("SELECT id, number FROM episodes WHERE season_id = ? ORDER BY number;", (season_id,))
                db_episodes = cur.fetchall()

                for ep_id, ep_num in db_episodes:
                    doc_ep = doc_episodes.get(ep_num)
                    if not doc_ep:
                        continue

                    # Extract question + option items from blocks
                    current_question = ""
                    extracted_items = []

                    for b in doc_ep.get("blocks", []):
                        btype = b.get("type")
                        btext = (b.get("text") or "").strip()
                        ch = b.get("choice")
                        if ch:
                            extracted_items.append((current_question, btext, ch))
                        else:
                            if btype in ("text", "note", "requirement") and len(btext) > 0:
                                current_question = btext

                    cur.execute("SELECT id, order_index FROM choices WHERE episode_id = ? ORDER BY order_index;", (ep_id,))
                    db_choices = cur.fetchall()

                    if not db_choices or not extracted_items:
                        continue

                    count_to_update = min(len(db_choices), len(extracted_items))
                    for idx in range(count_to_update):
                        ch_id = db_choices[idx][0]
                        q, opt_text, ch_data = extracted_items[idx]
                        
                        # Clean question text if needed
                        q_clean = q.strip() if q else ""
                        opt_clean = opt_text.strip() if opt_text else ch_data.get("text", "")

                        cur.execute("""
                            UPDATE choices
                            SET scene_title = ?,
                                text = ?,
                                recommended_option = ''
                            WHERE id = ?;
                        """, (q_clean, opt_clean, ch_id))
                        enriched_choices += 1

                    enriched_episodes += 1

        cur.execute("COMMIT;")
        print(f"[OK] Transaction committed: enriched {enriched_episodes} episodes, {enriched_choices} choices.")

    except Exception as e:
        cur.execute("ROLLBACK;")
        conn.close()
        raise RuntimeError(f"Enrichment failed, rolled back: {e}")

    # Post-verification
    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"
    cur.execute("PRAGMA foreign_key_check;")
    assert len(cur.fetchall()) == 0

    cur.execute("SELECT count(*) FROM stories;")
    stories_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM seasons;")
    seasons_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM episodes;")
    episodes_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM choices;")
    choices_cnt = cur.fetchone()[0]

    conn.close()

    assert stories_cnt == 58
    assert seasons_cnt == 144
    assert episodes_cnt == 1613
    assert choices_cnt == 53236

    post_size = db_path.stat().st_size
    post_sha = compute_sha256(db_path)
    print(f"[OK] Post-enrichment verification passed!")
    print(f"     Stories: {stories_cnt}, Seasons: {seasons_cnt}, Episodes: {episodes_cnt}, Choices: {choices_cnt}")
    print(f"     Size: {post_size} bytes | SHA-256: {post_sha}")

    return {
        "backup_path": str(backup_path),
        "enriched_episodes": enriched_episodes,
        "enriched_choices": enriched_choices,
        "post_sha": post_sha,
    }


if __name__ == "__main__":
    enrich_choices_and_episodes()
