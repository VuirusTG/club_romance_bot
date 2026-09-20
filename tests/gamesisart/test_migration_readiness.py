import json
import sqlite3
from pathlib import Path

import pytest

from scripts.gamesisart.migration_readiness import (
    IDENTITY_RESOLUTIONS,
    classify_multi_option,
    classify_production_choice,
    is_placeholder_choice,
    normalize_title,
    simulate_transactional_rollback,
)

def get_pre_migration_db() -> Path:
    backups = sorted(Path(".").glob("club_romance_before_gamesisart_migration_*.db"))
    if backups:
        return backups[-1]
    return Path("club_romance.db")

PROD_DB_PATH = get_pre_migration_db()
STAGING_DB_PATH = Path("data/gamesisart/staging.db")


def test_identity_resolutions_coverage() -> None:
    """Verify that all 12 unresolved production stories are documented with explicit resolution."""
    assert len(IDENTITY_RESOLUTIONS) == 12

    # Verify 7 ALIAS matches have valid target source keys
    alias_matches = [v for v in IDENTITY_RESOLUTIONS.values() if v["resolution"] == "MATCH"]
    assert len(alias_matches) == 7
    for am in alias_matches:
        assert am["target_source_key"].startswith("gamesisart:")
        assert am["action"] == "UPDATE_CANONICAL"

    # Verify 3 TEST/MANUAL records are marked SAFE_TO_IGNORE
    test_records = [v for v in IDENTITY_RESOLUTIONS.values() if v["resolution"] == "TEST_RECORD"]
    assert len(test_records) == 3
    for tr in test_records:
        assert tr["action"] == "SAFE_TO_IGNORE"

    # Verify 2 DUPLICATE records are marked MANUAL_REVIEW_REQUIRED
    duplicates = [v for v in IDENTITY_RESOLUTIONS.values() if v["resolution"] == "DUPLICATE"]
    assert len(duplicates) == 2
    for d in duplicates:
        assert d["action"] == "MANUAL_REVIEW_REQUIRED"


def test_title_normalization() -> None:
    """Verify normalization correctly bridges Cyrillic ё/е and punctuation."""
    assert normalize_title("Любовь со звёзд") == normalize_title("Любовь со Звезд")
    assert normalize_title("W: Ловчая времени") == "w  ловчая времени"
    assert normalize_title("Кали: Зов Тьмы") == "кали  зов тьмы"


def test_placeholder_classification_logic() -> None:
    """Verify placeholder detection accurately identifies stubs vs manual choices."""
    # Placeholders
    assert is_placeholder_choice("Краткий пункт выбора из импортированного прохождения", "gamesisart_import")
    assert is_placeholder_choice("Краткий пункт выбора...", None)
    assert is_placeholder_choice("Some option", "gamesisart_import")

    # Real choices
    assert not is_placeholder_choice("Кто поможет с первой зацепкой?", "romance,parameter")
    assert not is_placeholder_choice("Как попасть в архив?", "diamond,critical")
    assert not is_placeholder_choice("Взять за руку (15 к)", "romance")


def test_full_production_placeholder_audit() -> None:
    """Verify placeholder numbers against production DB (read-only)."""
    if not PROD_DB_PATH.exists():
        pytest.skip("Production DB not found")

    conn = sqlite3.connect(f"file:{PROD_DB_PATH.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Identify 42 matched story IDs
    prod_stories = cur.execute("SELECT id, title, guide_source_url FROM stories").fetchall()
    matched_ids: set[int] = set()
    unresolved_ids: set[int] = set(IDENTITY_RESOLUTIONS.keys())

    for ps in prod_stories:
        if ps["id"] not in unresolved_ids:
            matched_ids.add(ps["id"])

    assert len(matched_ids) == 42
    assert len(unresolved_ids) == 12

    # Query all choices
    all_choices = cur.execute(
        """
        SELECT c.id, c.text, c.tags, s.story_id
        FROM choices c
        JOIN episodes e ON c.episode_id = e.id
        JOIN seasons s ON e.season_id = s.id
        """
    ).fetchall()
    conn.close()

    assert len(all_choices) == 8235

    safe_replace_cnt = 0
    needs_review_cnt = 0
    no_match_cnt = 0

    for ch in all_choices:
        cls = classify_production_choice(
            choice_id=ch["id"],
            text=ch["text"],
            tags=ch["tags"],
            story_id=ch["story_id"],
            matched_story_ids=matched_ids,
        )
        if cls == "SAFE_TO_REPLACE":
            safe_replace_cnt += 1
        elif cls == "NEEDS_REVIEW":
            needs_review_cnt += 1
        elif cls == "NO_MATCH":
            no_match_cnt += 1

    assert safe_replace_cnt == 6279
    assert needs_review_cnt == 12
    assert no_match_cnt == 1944
    assert safe_replace_cnt + needs_review_cnt + no_match_cnt == 8235


def test_multi_option_classification_audit() -> None:
    """Verify deterministic categorization of all 4,012 multi-option blocks in staging DB."""
    if not STAGING_DB_PATH.exists():
        pytest.skip("Staging DB not found")

    conn = sqlite3.connect(f"file:{STAGING_DB_PATH.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, cost_diamonds, parameter_changes, character_effects, future_effects FROM staging_choices WHERE text LIKE '—%'"
    ).fetchall()
    conn.close()

    assert len(rows) == 4012

    counts = {"Category A": 0, "Category B": 0, "Category C": 0, "Category D": 0, "Category E": 0}
    for r in rows:
        cat = classify_multi_option(
            cost_diamonds=r["cost_diamonds"],
            parameter_changes=r["parameter_changes"],
            character_effects=r["character_effects"],
            future_effects=r["future_effects"],
        )
        counts[cat] += 1

    assert counts["Category A"] == 3545  # Cosmetic (outfits, hairstyles, rooms)
    assert counts["Category B"] == 40    # Free parameter effects only
    assert counts["Category C"] == 11    # Free romance effects only
    assert counts["Category D"] == 412   # Diamond with stats or romance
    assert counts["Category E"] == 4     # Combined / Ambiguous
    assert sum(counts.values()) == 4012


def test_production_id_preservation_and_foreign_keys() -> None:
    """Verify foreign keys schema guarantees safe in-place choice replacement."""
    if not PROD_DB_PATH.exists():
        pytest.skip("Production DB not found")

    conn = sqlite3.connect(f"file:{PROD_DB_PATH.resolve()}?mode=ro", uri=True)
    cur = conn.cursor()

    # Verify tables that reference stories, seasons, episodes
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    choices_inbound_fks = []
    for t in tables:
        fks = cur.execute(f"PRAGMA foreign_key_list({t})").fetchall()
        for fk in fks:
            if fk[2] == "choices":
                choices_inbound_fks.append((t, fk))

    # Choices table has ZERO inbound foreign keys
    assert len(choices_inbound_fks) == 0

    # User progress and subscriptions reference stories, seasons, episodes -> primary keys MUST be preserved
    progress_fks = [fk[2] for fk in cur.execute("PRAGMA foreign_key_list(progress)").fetchall()]
    assert "stories" in progress_fks
    assert "seasons" in progress_fks
    assert "episodes" in progress_fks

    subs_fks = [fk[2] for fk in cur.execute("PRAGMA foreign_key_list(subscriptions)").fetchall()]
    assert "stories" in subs_fks

    conn.close()


def test_transactional_rollback_simulation(tmp_path: Path) -> None:
    """Verify transactional rollback simulation restores DB to exact pristine state upon error."""
    if not PROD_DB_PATH.exists():
        pytest.skip("Production DB not found")

    temp_db = tmp_path / "rollback_test.db"
    res = simulate_transactional_rollback(PROD_DB_PATH, temp_db)

    assert res["rollback_occurred"] is True
    assert res["error_caught"] is not None
    assert "Simulated mid-migration failure" in res["error_caught"]
    assert res["integrity"] == "ok"
    assert res["counts_identical"] is True
    assert res["counts_after"] == res["counts_before"]
    assert res["db_intact"] is True
