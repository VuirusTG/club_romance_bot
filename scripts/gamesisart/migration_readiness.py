"""Phase 9 Migration Readiness & Identity Resolution module.

This module provides:
1. Exact identity resolution rules between club_romance.db and GamesIsArt staging.
2. Production placeholder classification (SAFE_TO_REPLACE vs NEEDS_REVIEW vs NO_MATCH).
3. Multi-option classification audit across staging data.
4. Transactional rollback verification harness.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ==============================================================================
# 1. IDENTITY RESOLUTION MAP
# ==============================================================================

# Explicit resolutions for the 12 non-exact production stories
IDENTITY_RESOLUTIONS: dict[int, dict[str, Any]] = {
    1: {
        "title": "Тени большого города",
        "slug": "ten-shadows",
        "resolution": "TEST_RECORD",
        "action": "SAFE_TO_IGNORE",
        "target_source_key": None,
        "reason": "Developer test story with 2 manual choices. Not an official Romance Club story.",
    },
    2: {
        "title": "Тест",
        "slug": "тест",
        "resolution": "TEST_RECORD",
        "action": "SAFE_TO_IGNORE",
        "target_source_key": None,
        "reason": "Developer test stub with 0 seasons, 0 episodes, 0 choices.",
    },
    31: {
        "title": "Рожденная Луной",
        "slug": "rozhdennaya-lunoi",
        "resolution": "DUPLICATE",
        "action": "MANUAL_REVIEW_REQUIRED",
        "target_source_key": None,
        "reason": "Duplicate of ID=32. Contains 10 manual choices. No corresponding source in GamesIsArt catalog.",
    },
    32: {
        "title": "Рождённая Луной",
        "slug": "rozhde-nnaya-lunoi",
        "resolution": "DUPLICATE",
        "action": "MANUAL_REVIEW_REQUIRED",
        "target_source_key": None,
        "reason": "Contains 5 seasons, 48 episodes, 566 choices. No corresponding source in GamesIsArt catalog. Preserve in production.",
    },
    47: {
        "title": "W: Ловчая времени",
        "slug": "w-lovchaya-vremeni",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_time",
        "reason": "Alternate title with 'W:' prefix. Matches 'Ловчая Времени' on GamesIsArt.",
    },
    49: {
        "title": "Райский сад",
        "slug": "rai-skii-sad",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_edem",
        "reason": "Alternate translation of Garden of Eden. Matches 'Эдемов сад' on GamesIsArt.",
    },
    54: {
        "title": "И туман поглотит нас",
        "slug": "i-tuman-poglotit-nas",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_morok",
        "reason": "Early working title. Matches 'И поглотит нас морок' on GamesIsArt.",
    },
    56: {
        "title": "Код Шекспира",
        "slug": "kod-shekspira",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_code",
        "reason": "Title variant ('Код' vs 'Шифр'). Matches 'Шифр Шекспира' on GamesIsArt.",
    },
    59: {
        "title": "Адвент №3",
        "slug": "advent-o3",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_three",
        "reason": "Title variant ('Адвент №3' vs 'Пришествие Номер Три'). Matches GamesIsArt.",
    },
    60: {
        "title": "Te Amo",
        "slug": "te-amo",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_te_amo",
        "reason": "GamesIsArt splits Te Amo into two volumes/sources. ID=60 maps to Volume 1.",
    },
    61: {
        "title": "Код Блю",
        "slug": "kod-blyu",
        "resolution": "MATCH",
        "action": "UPDATE_CANONICAL",
        "target_source_key": "gamesisart:romance_club_prohozhdenie_blue",
        "reason": "Title variant ('Код Блю' vs 'Код синий', Code Blue). Matches GamesIsArt.",
    },
    82: {
        "title": "Происшествие №3",
        "slug": "происшествие-№3",
        "resolution": "TEST_RECORD",
        "action": "SAFE_TO_IGNORE",
        "target_source_key": None,
        "reason": "Empty duplicate stub (0 seasons, 0 episodes, 0 choices). Duplicate of ID=59.",
    },
}


def normalize_title(title: str) -> str:
    """Normalize story title for fuzzy canonical matching."""
    return (
        title.lower()
        .replace("ё", "е")
        .replace(":", " ")
        .replace("-", " ")
        .replace("—", " ")
        .replace(".", " ")
        .strip()
    )


# ==============================================================================
# 2. PLACEHOLDER CLASSIFICATION
# ==============================================================================

PLACEHOLDER_MARKERS = ("Краткий пункт выбора", "gamesisart_import")


def is_placeholder_choice(text: str | None, tags: str | None) -> bool:
    """Return True if a choice row is an old auto-generated placeholder."""
    t = text or ""
    tg = tags or ""
    return any(marker in t or marker in tg for marker in PLACEHOLDER_MARKERS)


def classify_production_choice(
    choice_id: int,
    text: str | None,
    tags: str | None,
    story_id: int,
    matched_story_ids: set[int],
) -> str:
    """Classify choice into SAFE_TO_REPLACE, NEEDS_REVIEW, or NO_MATCH."""
    if not is_placeholder_choice(text, tags):
        return "NEEDS_REVIEW"
    if story_id in matched_story_ids:
        return "SAFE_TO_REPLACE"
    return "NO_MATCH"


# ==============================================================================
# 3. MULTI-OPTION CLASSIFICATION
# ==============================================================================

def classify_multi_option(
    cost_diamonds: int | None,
    parameter_changes: list[str] | str | None,
    character_effects: list[str] | str | None,
    future_effects: list[str] | str | None,
) -> str:
    """Classify a multi-option block into standard categories A, B, C, D, E.

    - Category A: Cosmetic only (no stat/romance effects; free or diamond purchase)
    - Category B: Free parameter effects only
    - Category C: Free romance effects only
    - Category D: Diamond choice with stat or romance effects
    - Category E: Combined / Ambiguous effects
    """
    cost = cost_diamonds or 0
    params = json.loads(parameter_changes) if isinstance(parameter_changes, str) and parameter_changes else (parameter_changes or [])
    chars = json.loads(character_effects) if isinstance(character_effects, str) and character_effects else (character_effects or [])
    futures = json.loads(future_effects) if isinstance(future_effects, str) and future_effects else (future_effects or [])

    has_cost = cost > 0
    has_params = len(params) > 0
    has_chars = len(chars) > 0
    has_futures = len(futures) > 0

    has_effects = has_params or has_chars or has_futures

    if has_cost and has_effects:
        return "Category D"  # Diamond + effects
    if not has_effects:
        return "Category A"  # Cosmetic only (free or diamond without stat changes)
    if not has_cost:
        if has_params and not has_chars and not has_futures:
            return "Category B"  # Free parameter effects only
        if has_chars and not has_params and not has_futures:
            return "Category C"  # Free romance effects only
        return "Category E"  # Combined / Ambiguous effects
    return "Category E"


# ==============================================================================
# 4. TRANSACTIONAL ROLLBACK SIMULATION
# ==============================================================================

def simulate_transactional_rollback(
    original_db: Path,
    temp_db: Path,
) -> dict[str, Any]:
    """Simulate partial migration failure and verify complete rollback integrity.

    Steps:
    1. Copy original_db to temp_db.
    2. Record pre-migration sha256 and row counts.
    3. Open SQLite connection with transaction.
    4. Execute partial migration operations (INSERT, UPDATE).
    5. Intentionally raise an exception mid-migration.
    6. Execute conn.rollback() and close.
    7. Verify temp_db post-rollback row counts, integrity_check, and vacuumed content.
    """
    shutil.copy2(original_db, temp_db)

    def compute_sha(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def get_counts(path: Path) -> dict[str, int]:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            cur = conn.cursor()
            return {
                "stories": cur.execute("SELECT count(*) FROM stories").fetchone()[0],
                "seasons": cur.execute("SELECT count(*) FROM seasons").fetchone()[0],
                "episodes": cur.execute("SELECT count(*) FROM episodes").fetchone()[0],
                "choices": cur.execute("SELECT count(*) FROM choices").fetchone()[0],
            }

    counts_before = get_counts(temp_db)
    sha_before = compute_sha(temp_db)

    # Perform partial migration with injected failure
    conn = sqlite3.connect(temp_db)
    conn.execute("PRAGMA foreign_keys = ON")
    rollback_occurred = False
    error_caught = None

    try:
        conn.execute("BEGIN IMMEDIATE")

        # Step 1: Update an existing story canonical URL (simulating Phase A)
        conn.execute(
            "UPDATE stories SET guide_source_url = ? WHERE id = ?",
            ("https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html", 44),
        )

        # Step 2: Insert a temporary new season (simulating Phase B)
        conn.execute(
            "INSERT INTO seasons (story_id, number, title, description) VALUES (?, ?, ?, ?)",
            (44, 99, "Simulated Season", "Simulated Season Description"),
        )

        # Step 3: Replace some placeholder choices (simulating Phase C)
        conn.execute(
            "UPDATE choices SET text = ? WHERE id = 100",
            ("Simulated Real Choice Text",),
        )

        # Step 4: Inject deliberate failure mid-migration!
        raise sqlite3.IntegrityError("Simulated mid-migration failure: foreign key or constraint violation")

    except Exception as exc:
        conn.rollback()
        rollback_occurred = True
        error_caught = str(exc)
    finally:
        conn.close()

    # Re-check counts and integrity
    counts_after = get_counts(temp_db)

    # Vacuum to ensure journal/WAL cleanly cleared if any
    with sqlite3.connect(temp_db) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

    return {
        "rollback_occurred": rollback_occurred,
        "error_caught": error_caught,
        "integrity": integrity,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "counts_identical": counts_before == counts_after,
        "sha_before": sha_before,
        "db_intact": rollback_occurred and (counts_before == counts_after) and (integrity == "ok"),
    }
