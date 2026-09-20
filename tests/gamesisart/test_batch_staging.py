import json
import sqlite3
from pathlib import Path

import pytest

from scripts.gamesisart.models import Block, ChoiceDocument, EpisodeDocument, SeasonDocument, StoryDocument
from scripts.gamesisart.staging import (
    BatchSourceRecord,
    BatchStagingReport,
    StagingDatabase,
    diff_story_with_production,
    run_batch_staging,
    run_full_production_diff,
)


def make_mock_doc(key: str, title: str) -> StoryDocument:
    choices = [ChoiceDocument(order=1, text="Sample Choice", cost_diamonds=10)]
    episodes = [
        EpisodeDocument(
            number=1,
            title="Episode 1",
            blocks=[Block(order=1, type="choice", text="Sample Choice", choice=choices[0])],
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


def test_batch_error_isolation(tmp_path: Path) -> None:
    """One broken source must not halt the batch; errors must be recorded."""
    mock_sources_file = tmp_path / "mock_sources.json"
    mock_sources = {
        "sources": [
            {
                "source_key": "gamesisart:valid_1",
                "canonical_url": "http://127.0.0.1:9/broken.html",
                "source_title": "Broken Source",
            }
        ]
    }
    mock_sources_file.write_text(json.dumps(mock_sources), encoding="utf-8")

    st_db_path = tmp_path / "staging.db"
    report = run_batch_staging(
        sources_path=mock_sources_file,
        raw_dir=tmp_path / "raw",
        parsed_dir=tmp_path / "parsed",
        staging_db_path=st_db_path,
    )

    assert report.total_sources == 1
    assert report.failed_count == 1
    assert report.success_count == 0
    assert len(report.sources) == 1
    assert report.sources[0].status == "FAILED_PARSE"
    assert "Broken Source" in report.sources[0].source_title
    assert len(report.sources[0].errors) > 0


def test_staging_isolation_and_production_untouched(tmp_path: Path) -> None:
    """Staging operations must not touch production DB."""
    prod_db = Path("club_romance.db")
    mtime_before = prod_db.stat().st_mtime_ns
    size_before = prod_db.stat().st_size

    st_db_path = tmp_path / "staging_iso.db"
    st_db = StagingDatabase(db_path=st_db_path)
    doc = make_mock_doc("gamesisart:iso_test", "Iso Story")
    st_db.import_story(doc, content_hash="hash_iso")

    assert st_db_path.exists()
    assert prod_db.stat().st_mtime_ns == mtime_before
    assert prod_db.stat().st_size == size_before


def test_batch_statistics_internal_consistency() -> None:
    records = [
        BatchSourceRecord(
            source_key="s1",
            canonical_url="u1",
            source_title="T1",
            status="SUCCESS",
            seasons=2,
            episodes=10,
            choices=50,
            diamond_choices=10,
        ),
        BatchSourceRecord(
            source_key="s2",
            canonical_url="u2",
            source_title="T2",
            status="UP_TO_DATE",
            seasons=1,
            episodes=5,
            choices=25,
            diamond_choices=5,
        ),
        BatchSourceRecord(
            source_key="s3",
            canonical_url="u3",
            source_title="T3",
            status="FAILED_PARSE",
            errors_count=1,
        ),
    ]

    report = BatchStagingReport(
        total_sources=3,
        success_count=1,
        up_to_date_count=1,
        failed_count=1,
        total_time_seconds=1.5,
        aggregate_metrics={
            "stories": 2,
            "seasons": sum(r.seasons for r in records),
            "episodes": sum(r.episodes for r in records),
            "choices": sum(r.choices for r in records),
            "diamond_choices": sum(r.diamond_choices for r in records),
        },
        sources=records,
    )

    assert report.total_sources == report.success_count + report.up_to_date_count + report.failed_count
    assert report.aggregate_metrics["stories"] == 2
    assert report.aggregate_metrics["seasons"] == 3
    assert report.aggregate_metrics["episodes"] == 15
    assert report.aggregate_metrics["choices"] == 75
    assert report.aggregate_metrics["diamond_choices"] == 15


def test_full_diff_read_only(tmp_path: Path) -> None:
    backups = sorted(Path(".").glob("club_romance_before_gamesisart_migration_*.db"))
    prod_db = backups[-1] if backups else Path("club_romance.db")
    mtime_before = prod_db.stat().st_mtime_ns
    size_before = prod_db.stat().st_size

    # Single-record mock report
    mock_report = BatchStagingReport(
        total_sources=1,
        success_count=1,
        up_to_date_count=0,
        failed_count=0,
        total_time_seconds=0.1,
        aggregate_metrics={},
        sources=[
            BatchSourceRecord(
                source_key="gamesisart:romance_club_prohozhdenie_seven",
                canonical_url="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html",
                source_title="7 братьев",
                status="SUCCESS",
            )
        ],
    )

    full_diff = run_full_production_diff(mock_report, prod_db_path=prod_db)

    assert full_diff.total_prod_stories == 54
    assert full_diff.placeholder_audit["total_placeholders"] > 8000
    assert full_diff.matched_stories >= 1
    # Verify prod DB was not modified
    assert prod_db.stat().st_mtime_ns == mtime_before
    assert prod_db.stat().st_size == size_before
