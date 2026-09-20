import sqlite3
import tempfile
from pathlib import Path

import pytest

from scripts.gamesisart.models import Block, ChoiceDocument, EpisodeDocument, SeasonDocument, StoryDocument
from scripts.gamesisart.staging import (
    StagingDatabase,
    compute_content_hash,
    diff_story_with_production,
    run_dry_run,
)


def make_sample_doc(key: str = "gamesisart:test_story", title: str = "Test Story") -> StoryDocument:
    choices = [
        ChoiceDocument(order=1, text="Choice A", cost_diamonds=0, parameter_changes=["+1 stat"]),
        ChoiceDocument(order=2, text="Choice B (15 к)", cost_diamonds=15),
    ]
    episodes = [
        EpisodeDocument(
            number=1,
            title="Ep 1",
            blocks=[
                Block(order=1, type="choice", text="Choice A", choice=choices[0]),
                Block(order=2, type="choice", text="Choice B (15 к)", choice=choices[1]),
            ],
        )
    ]
    seasons = [SeasonDocument(number=1, title="Season 1", episodes=episodes)]
    return StoryDocument(
        parser_version="1.2.0",
        source="gamesisart",
        source_key=key,
        source_url=f"https://gamesisart.ru/guide/{key}.html",
        canonical_url=f"https://gamesisart.ru/guide/{key}.html",
        source_title=title,
        seasons=seasons,
    )


def test_content_hash_deterministic() -> None:
    h1 = compute_content_hash(["<html>test</html>", "<b>part2</b>"])
    h2 = compute_content_hash(["<html>test</html>", "<b>part2</b>"])
    h3 = compute_content_hash(["<html>diff</html>"])
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256


def test_staging_db_creation_and_isolation(tmp_path: Path) -> None:
    db_file = tmp_path / "test_staging.db"
    st_db = StagingDatabase(db_path=db_file)
    assert db_file.exists()
    summary = st_db.get_source_summary("non_existent")
    assert summary is None


def test_staging_import_run1_run2_idempotency(tmp_path: Path) -> None:
    db_file = tmp_path / "test_staging.db"
    st_db = StagingDatabase(db_path=db_file)
    doc = make_sample_doc()

    # Run 1: initial insert
    res1 = st_db.import_story(doc, content_hash="hash_v1")
    assert res1["status"] == "STAGED"
    sum1 = st_db.get_source_summary(doc.source_key)
    assert sum1 is not None
    assert sum1["seasons"] == 1
    assert sum1["episodes"] == 1
    assert sum1["choices"] == 2

    # Run 2: same source, same hash -> UP_TO_DATE (no-op)
    res2 = st_db.import_story(doc, content_hash="hash_v1")
    assert res2["status"] == "UP_TO_DATE"
    sum2 = st_db.get_source_summary(doc.source_key)
    assert sum2 is not None
    assert sum2["seasons"] == 1
    assert sum2["episodes"] == 1
    assert sum2["choices"] == 2

    # Run 3: force reload -> re-imports without any duplicate records
    res3 = st_db.import_story(doc, content_hash="hash_v1", force=True)
    assert res3["status"] == "STAGED"
    sum3 = st_db.get_source_summary(doc.source_key)
    assert sum3 is not None
    assert sum3["seasons"] == 1
    assert sum3["episodes"] == 1
    assert sum3["choices"] == 2


def test_diff_with_production_read_only(tmp_path: Path) -> None:
    # Create a mock production DB
    prod_db = tmp_path / "mock_prod.db"
    with sqlite3.connect(prod_db) as conn:
        conn.executescript(
            """
            CREATE TABLE stories (id INTEGER PRIMARY KEY, title TEXT, slug TEXT, guide_source_name TEXT, guide_source_url TEXT);
            CREATE TABLE seasons (id INTEGER PRIMARY KEY, story_id INTEGER, number INTEGER, title TEXT);
            CREATE TABLE episodes (id INTEGER PRIMARY KEY, season_id INTEGER, number INTEGER, title TEXT, summary TEXT, guide_intro TEXT);
            CREATE TABLE choices (id INTEGER PRIMARY KEY, episode_id INTEGER, order_index INTEGER, text TEXT, cost_diamonds INTEGER, tags TEXT);

            INSERT INTO stories VALUES (1, 'Test Story', 'test-story', 'GamesIsArt.ru', 'https://gamesisart.ru/old.html');
            INSERT INTO seasons VALUES (10, 1, 1, 'Season 1');
            INSERT INTO episodes VALUES (100, 10, 1, 'Ep 1', 'summary', 'intro');
            INSERT INTO choices VALUES (1000, 100, 1, 'Краткий пункт выбора из импортированного прохождения', 0, 'gamesisart_import');
            """
        )

    doc = make_sample_doc()
    diff = diff_story_with_production(doc, prod_db_path=prod_db)

    assert diff.story_status == "MATCH"
    assert diff.seasons_summary["MATCH"] == 1
    assert diff.seasons_summary["NEW"] == 0
    assert diff.episodes_summary["MATCH"] == 1
    assert diff.choices_summary["PLACEHOLDER_REPLACE"] == 2  # parsed doc has 2 real choices


def test_diff_with_new_story(tmp_path: Path) -> None:
    prod_db = tmp_path / "mock_empty_prod.db"
    with sqlite3.connect(prod_db) as conn:
        conn.executescript(
            """
            CREATE TABLE stories (id INTEGER PRIMARY KEY, title TEXT, slug TEXT, guide_source_name TEXT, guide_source_url TEXT);
            CREATE TABLE seasons (id INTEGER PRIMARY KEY, story_id INTEGER, number INTEGER, title TEXT);
            CREATE TABLE episodes (id INTEGER PRIMARY KEY, season_id INTEGER, number INTEGER, title TEXT, summary TEXT, guide_intro TEXT);
            CREATE TABLE choices (id INTEGER PRIMARY KEY, episode_id INTEGER, order_index INTEGER, text TEXT, cost_diamonds INTEGER, tags TEXT);
            """
        )

    doc = make_sample_doc(key="gamesisart:brand_new", title="Brand New Story")
    diff = diff_story_with_production(doc, prod_db_path=prod_db)

    assert diff.story_status == "NEW"
    assert diff.seasons_summary["NEW"] == 1
    assert diff.episodes_summary["NEW"] == 1
    assert diff.choices_summary["NEW"] == 2


def test_dry_run_does_not_modify_production_db() -> None:
    prod_db = Path("club_romance.db")
    mtime_before = prod_db.stat().st_mtime_ns
    size_before = prod_db.stat().st_size

    # Run dry run
    report_data = run_dry_run("https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html", prod_db_path=prod_db)

    assert report_data["status"] == "OK"
    assert report_data["diff"]["story_status"] == "MATCH"
    assert prod_db.stat().st_mtime_ns == mtime_before
    assert prod_db.stat().st_size == size_before
