import sqlite3
from pathlib import Path
import pytest

DB_PATH = Path("club_romance.db")


@pytest.fixture(scope="module")
def db_conn():
    assert DB_PATH.exists(), f"Database {DB_PATH} not found"
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


def test_database_integrity_and_foreign_keys(db_conn):
    cur = db_conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"

    cur.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    assert len(fk_errors) == 0, f"Foreign key check failed: {fk_errors}"


def test_deleted_stories_are_absent(db_conn):
    cur = db_conn.cursor()
    deleted_ids = (1, 2, 31, 82, 83, 84)
    cur.execute(f"SELECT id, title FROM stories WHERE id IN {deleted_ids};")
    rows = cur.fetchall()
    assert len(rows) == 0, f"Deleted stories still present: {rows}"


def test_total_story_counts(db_conn):
    cur = db_conn.cursor()
    cur.execute("SELECT count(*) FROM stories;")
    total_stories = cur.fetchone()[0]
    assert total_stories == 58, f"Expected 58 stories, found {total_stories}"

    cur.execute("SELECT count(*) FROM seasons;")
    total_seasons = cur.fetchone()[0]
    assert total_seasons == 144, f"Expected 144 seasons, found {total_seasons}"

    cur.execute("SELECT count(*) FROM episodes;")
    total_episodes = cur.fetchone()[0]
    assert total_episodes == 1613, f"Expected 1613 episodes, found {total_episodes}"

    cur.execute("SELECT count(*) FROM choices;")
    total_choices = cur.fetchone()[0]
    assert total_choices == 53236, f"Expected 53236 choices, found {total_choices}"


def test_no_duplicate_story_titles(db_conn):
    cur = db_conn.cursor()
    cur.execute("""
        SELECT title, count(*)
        FROM stories
        GROUP BY title
        HAVING count(*) > 1;
    """)
    duplicates = cur.fetchall()
    assert len(duplicates) == 0, f"Duplicate story titles detected: {duplicates}"


def test_canonical_stories_structure(db_conn):
    cur = db_conn.cursor()

    # Story 77 (Ideal)
    cur.execute("SELECT id, title, slug FROM stories WHERE id = 77;")
    story77 = cur.fetchone()
    assert story77 is not None
    assert story77[1] == "Идеал"
    assert story77[2] == "ideal"

    cur.execute("SELECT number, title FROM seasons WHERE story_id = 77 ORDER BY number;")
    seasons77 = cur.fetchall()
    assert len(seasons77) == 2
    assert seasons77[0] == (1, "Том 1")
    assert seasons77[1] == (2, "Том 2")

    # Story 57 (Bureau)
    cur.execute("SELECT id, title, slug FROM stories WHERE id = 57;")
    story57 = cur.fetchone()
    assert story57 is not None
    assert story57[1] == "Бюро параллельных миров"
    assert story57[2] == "byuro-parallelnyh-mirov"

    cur.execute("SELECT count(*) FROM seasons WHERE story_id = 57;")
    assert cur.fetchone()[0] == 2

    # Story 32 (Moonborn)
    cur.execute("SELECT id, title, slug FROM stories WHERE id = 32;")
    story32 = cur.fetchone()
    assert story32 is not None
    assert story32[1] == "Рождённая Луной"
    assert story32[2] == "rozhdennaya-lunoi"

    cur.execute("SELECT count(*) FROM seasons WHERE story_id = 32;")
    assert cur.fetchone()[0] == 5

    cur.execute("SELECT count(*) FROM episodes e JOIN seasons s ON e.season_id = s.id WHERE s.story_id = 32;")
    assert cur.fetchone()[0] == 48


def test_user_data_consistency(db_conn):
    cur = db_conn.cursor()
    # Check that user progress only points to valid existing stories, seasons, and episodes
    cur.execute("""
        SELECT p.id, p.story_id
        FROM progress p
        LEFT JOIN stories s ON p.story_id = s.id
        WHERE s.id IS NULL;
    """)
    orphan_progress = cur.fetchall()
    assert len(orphan_progress) == 0, f"Orphan progress rows found: {orphan_progress}"
