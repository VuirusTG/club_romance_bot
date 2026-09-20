"""Safe Staging & Import Pipeline for GamesIsArt guides.

This module provides:
1. Content hash & versioning (sha256 of raw HTML, parser version check).
2. Staging SQLite Database (data/gamesisart/staging.db), totally isolated from production.
3. Read-only Diff Engine against club_romance.db (Story, Season, Episode, Choice).
4. Dry-Run mechanism: parse -> validate -> compare -> report with zero SQLite writes.
5. Idempotent import into staging with deduplication.
6. Batch Staging: processes all discovered sources with error isolation.
7. Full Batch Diff & Placeholder Analysis across production DB.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.gamesisart.models import ChoiceDocument, EpisodeDocument, SeasonDocument, StoryDocument
from scripts.gamesisart.parser import (
    DEFAULT_PARSED_DIR,
    DEFAULT_RAW_DIR,
    PARSER_VERSION,
    SOURCE,
    load_or_fetch_raw,
    parse_story_from_url,
    parser_summary,
    raw_filename_for_url,
)
from scripts.gamesisart.validator import validate_story_document

DEFAULT_STAGING_DB_PATH = Path("data/gamesisart/staging.db")
DEFAULT_PROD_DB_PATH = Path("club_romance.db")
DEFAULT_DISCOVERED_SOURCES_PATH = Path("data/gamesisart/discovered_sources.json")


def compute_content_hash(raw_texts: list[str | bytes]) -> str:
    """Compute sha256 content hash of all raw HTML pages of a story."""
    hasher = hashlib.sha256()
    for item in raw_texts:
        data = item.encode("utf-8") if isinstance(item, str) else item
        hasher.update(data)
    return hasher.hexdigest()


def compute_story_content_hash(page_urls: list[str], raw_dir: Path = DEFAULT_RAW_DIR) -> str:
    """Compute content hash for a story by loading its raw files."""
    texts: list[str] = []
    for url in sorted(page_urls):
        p = raw_dir / raw_filename_for_url(url)
        if p.exists():
            texts.append(p.read_text(encoding="utf-8"))
    return compute_content_hash(texts) if texts else ""


@dataclass
class DiffItem:
    entity: str  # "story" | "season" | "episode" | "choice"
    identity: str
    status: str  # "MATCH" | "NEW" | "CHANGED" | "DUPLICATE" | "CONFLICT" | "UNRESOLVED"
    details: str
    existing_id: int | None = None
    parsed_value: Any = None
    existing_value: Any = None


@dataclass
class DiffReport:
    story_title: str
    source_key: str
    canonical_url: str
    story_status: str
    seasons_summary: dict[str, int] = field(default_factory=dict)
    episodes_summary: dict[str, int] = field(default_factory=dict)
    choices_summary: dict[str, int] = field(default_factory=dict)
    items: list[DiffItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StagingDatabase:
    """Isolated SQLite database for staging parsed GamesIsArt guides.

    Completely independent of production club_romance.db.
    """

    def __init__(self, db_path: Path = DEFAULT_STAGING_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS staging_sources (
                    source_key TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    page_urls TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'staged',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS staging_stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_key) REFERENCES staging_sources(source_key) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS staging_seasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    UNIQUE(source_key, number),
                    FOREIGN KEY (source_key) REFERENCES staging_sources(source_key) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS staging_episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    season_number INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    blocks_count INTEGER NOT NULL DEFAULT 0,
                    choices_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(source_key, season_number, episode_number),
                    FOREIGN KEY (source_key) REFERENCES staging_sources(source_key) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS staging_choices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    season_number INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    order_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    cost_diamonds INTEGER NOT NULL DEFAULT 0,
                    parameter_changes TEXT NOT NULL DEFAULT '[]',
                    character_effects TEXT NOT NULL DEFAULT '[]',
                    future_effects TEXT NOT NULL DEFAULT '[]',
                    is_critical INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]',
                    UNIQUE(source_key, season_number, episode_number, order_index),
                    FOREIGN KEY (source_key) REFERENCES staging_sources(source_key) ON DELETE CASCADE
                );
                """
            )

    def is_up_to_date(self, source_key: str, content_hash: str, parser_version: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT content_hash, parser_version FROM staging_sources WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if not row:
                return False
            return row["content_hash"] == content_hash and row["parser_version"] == parser_version

    def import_story(
        self,
        doc: StoryDocument,
        content_hash: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        """Idempotently import or update a StoryDocument in the staging DB."""
        now = datetime.now(timezone.utc).isoformat()
        page_urls = doc.metadata.get("page_urls", [doc.source_url])
        if not content_hash:
            content_hash = compute_story_content_hash(page_urls)

        # Check if identical already
        if not force and self.is_up_to_date(doc.source_key, content_hash, doc.parser_version):
            return {
                "status": "UP_TO_DATE",
                "source_key": doc.source_key,
                "content_hash": content_hash,
                "seasons": len(doc.seasons),
                "episodes": sum(len(s.episodes) for s in doc.seasons),
                "choices": sum(
                    1 for s in doc.seasons for ep in s.episodes for b in ep.blocks if b.choice
                ),
            }

        with self._get_connection() as conn:
            # Atomic transaction
            conn.execute("BEGIN TRANSACTION")
            # 1. Upsert source record
            conn.execute(
                """
                INSERT INTO staging_sources
                    (source_key, canonical_url, source_title, parser_version, content_hash, page_urls, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'staged', ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    canonical_url = excluded.canonical_url,
                    source_title = excluded.source_title,
                    parser_version = excluded.parser_version,
                    content_hash = excluded.content_hash,
                    page_urls = excluded.page_urls,
                    status = 'updated',
                    updated_at = excluded.updated_at
                """,
                (
                    doc.source_key,
                    doc.canonical_url,
                    doc.source_title,
                    doc.parser_version,
                    content_hash,
                    json.dumps(page_urls),
                    now,
                    now,
                ),
            )

            # Clear previous child records for clean idempotent reload
            conn.execute("DELETE FROM staging_choices WHERE source_key = ?", (doc.source_key,))
            conn.execute("DELETE FROM staging_episodes WHERE source_key = ?", (doc.source_key,))
            conn.execute("DELETE FROM staging_seasons WHERE source_key = ?", (doc.source_key,))
            conn.execute("DELETE FROM staging_stories WHERE source_key = ?", (doc.source_key,))

            # 2. Insert story
            conn.execute(
                """
                INSERT INTO staging_stories (source_key, title, canonical_url, parser_version, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (doc.source_key, doc.source_title, doc.canonical_url, doc.parser_version, content_hash, now),
            )

            # 3. Insert seasons, episodes, choices
            total_episodes = 0
            total_choices = 0

            for season in doc.seasons:
                conn.execute(
                    "INSERT INTO staging_seasons (source_key, number, title) VALUES (?, ?, ?)",
                    (doc.source_key, season.number, season.title),
                )
                for episode in season.episodes:
                    total_episodes += 1
                    ep_choices = [b for b in episode.blocks if b.choice]
                    conn.execute(
                        """
                        INSERT INTO staging_episodes
                            (source_key, season_number, episode_number, title, blocks_count, choices_count)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc.source_key,
                            season.number,
                            episode.number,
                            episode.title,
                            len(episode.blocks),
                            len(ep_choices),
                        ),
                    )
                    choice_idx = 1
                    for block in episode.blocks:
                        if not block.choice:
                            continue
                        total_choices += 1
                        ch = block.choice
                        conn.execute(
                            """
                            INSERT INTO staging_choices
                                (source_key, season_number, episode_number, order_index, text, cost_diamonds,
                                 parameter_changes, character_effects, future_effects, is_critical, tags)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                doc.source_key,
                                season.number,
                                episode.number,
                                choice_idx,
                                ch.text,
                                ch.cost_diamonds,
                                json.dumps(ch.parameter_changes, ensure_ascii=False),
                                json.dumps(ch.character_effects, ensure_ascii=False),
                                json.dumps(ch.future_effects, ensure_ascii=False),
                                1 if ch.is_critical else 0,
                                json.dumps(ch.tags, ensure_ascii=False),
                            ),
                        )
                        choice_idx += 1

            conn.commit()

        return {
            "status": "STAGED",
            "source_key": doc.source_key,
            "content_hash": content_hash,
            "seasons": len(doc.seasons),
            "episodes": total_episodes,
            "choices": total_choices,
        }

    def get_source_summary(self, source_key: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            src = conn.execute("SELECT * FROM staging_sources WHERE source_key = ?", (source_key,)).fetchone()
            if not src:
                return None
            seasons_count = conn.execute(
                "SELECT count(*) FROM staging_seasons WHERE source_key = ?", (source_key,)
            ).fetchone()[0]
            episodes_count = conn.execute(
                "SELECT count(*) FROM staging_episodes WHERE source_key = ?", (source_key,)
            ).fetchone()[0]
            choices_count = conn.execute(
                "SELECT count(*) FROM staging_choices WHERE source_key = ?", (source_key,)
            ).fetchone()[0]
            return {
                "source_key": src["source_key"],
                "canonical_url": src["canonical_url"],
                "source_title": src["source_title"],
                "parser_version": src["parser_version"],
                "content_hash": src["content_hash"],
                "status": src["status"],
                "seasons": seasons_count,
                "episodes": episodes_count,
                "choices": choices_count,
                "created_at": src["created_at"],
                "updated_at": src["updated_at"],
            }

    def get_all_source_summaries(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM staging_sources ORDER BY source_title").fetchall()
            summaries = []
            for r in rows:
                sk = r["source_key"]
                seasons_count = conn.execute("SELECT count(*) FROM staging_seasons WHERE source_key = ?", (sk,)).fetchone()[0]
                episodes_count = conn.execute("SELECT count(*) FROM staging_episodes WHERE source_key = ?", (sk,)).fetchone()[0]
                choices_count = conn.execute("SELECT count(*) FROM staging_choices WHERE source_key = ?", (sk,)).fetchone()[0]
                summaries.append({
                    "source_key": sk,
                    "canonical_url": r["canonical_url"],
                    "source_title": r["source_title"],
                    "parser_version": r["parser_version"],
                    "content_hash": r["content_hash"],
                    "status": r["status"],
                    "seasons": seasons_count,
                    "episodes": episodes_count,
                    "choices": choices_count,
                })
            return summaries


def diff_story_with_production(
    doc: StoryDocument,
    prod_db_path: Path = DEFAULT_PROD_DB_PATH,
) -> DiffReport:
    """Compare parsed StoryDocument with existing production SQLite database.

    Strictly READ-ONLY (uses uri=True with mode=ro).
    Zero modifications to production database.
    """
    db_file = Path(prod_db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"Production database not found: {prod_db_path}")

    report = DiffReport(
        story_title=doc.source_title,
        source_key=doc.source_key,
        canonical_url=doc.canonical_url,
        story_status="NEW",
    )

    conn = sqlite3.connect(f"file:{db_file.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # 1. Match Story
        # Search by exact title or canonical guide_source_url
        cur.execute(
            "SELECT id, title, slug, guide_source_name, guide_source_url FROM stories WHERE title = ? OR guide_source_url = ?",
            (doc.source_title, doc.canonical_url),
        )
        existing_story = cur.fetchone()

        if existing_story:
            report.story_status = "MATCH"
            is_url_changed = existing_story["guide_source_url"] != doc.canonical_url
            status_desc = "Story exists in production"
            if is_url_changed:
                status_desc += f" (guide_source_url changed: {existing_story['guide_source_url']} -> {doc.canonical_url})"
            report.items.append(
                DiffItem(
                    entity="story",
                    identity=doc.source_key,
                    status="CHANGED" if is_url_changed else "MATCH",
                    details=status_desc,
                    existing_id=existing_story["id"],
                    parsed_value={"title": doc.source_title, "url": doc.canonical_url},
                    existing_value={
                        "title": existing_story["title"],
                        "url": existing_story["guide_source_url"],
                    },
                )
            )
            story_id = existing_story["id"]
        else:
            report.story_status = "NEW"
            report.items.append(
                DiffItem(
                    entity="story",
                    identity=doc.source_key,
                    status="NEW",
                    details=f"Story not found in production DB. Will be created as '{doc.source_title}'",
                    parsed_value={"title": doc.source_title, "url": doc.canonical_url},
                )
            )
            story_id = None

        # 2. Match Seasons & Episodes
        seasons_stat = {"MATCH": 0, "NEW": 0, "CHANGED": 0}
        episodes_stat = {"MATCH": 0, "NEW": 0, "CHANGED": 0}
        choices_stat = {"MATCH": 0, "NEW": 0, "CHANGED": 0, "PLACEHOLDER_REPLACE": 0}

        for season in doc.seasons:
            existing_season = None
            if story_id is not None:
                cur.execute(
                    "SELECT id, number, title FROM seasons WHERE story_id = ? AND number = ?",
                    (story_id, season.number),
                )
                existing_season = cur.fetchone()

            if existing_season:
                seasons_stat["MATCH"] += 1
                report.items.append(
                    DiffItem(
                        entity="season",
                        identity=f"{doc.source_key}:s{season.number}",
                        status="MATCH",
                        details=f"Season {season.number} exists (id={existing_season['id']})",
                        existing_id=existing_season["id"],
                    )
                )
                season_id = existing_season["id"]
            else:
                seasons_stat["NEW"] += 1
                report.items.append(
                    DiffItem(
                        entity="season",
                        identity=f"{doc.source_key}:s{season.number}",
                        status="NEW",
                        details=f"Season {season.number} is NEW in production",
                    )
                )
                season_id = None

            for episode in season.episodes:
                existing_episode = None
                if season_id is not None:
                    cur.execute(
                        "SELECT id, number, title, summary, guide_intro FROM episodes WHERE season_id = ? AND number = ?",
                        (season_id, episode.number),
                    )
                    existing_episode = cur.fetchone()

                parsed_choices = [b.choice for b in episode.blocks if b.choice]

                if existing_episode:
                    episodes_stat["MATCH"] += 1
                    ep_id = existing_episode["id"]
                    report.items.append(
                        DiffItem(
                            entity="episode",
                            identity=f"{doc.source_key}:s{season.number}:e{episode.number}",
                            status="MATCH",
                            details=f"Episode {season.number}.{episode.number} exists (id={ep_id}, title='{existing_episode['title']}')",
                            existing_id=ep_id,
                        )
                    )

                    # Check existing choices in episode
                    cur.execute(
                        "SELECT id, order_index, text, cost_diamonds, tags FROM choices WHERE episode_id = ? ORDER BY order_index",
                        (ep_id,),
                    )
                    existing_choices = cur.fetchall()

                    # Check if existing choices are old placeholders
                    has_placeholders = any(
                        "Краткий пункт выбора" in (ch["text"] or "") or "gamesisart_import" in (ch["tags"] or "")
                        for ch in existing_choices
                    )

                    if has_placeholders:
                        choices_stat["PLACEHOLDER_REPLACE"] += len(parsed_choices)
                        report.items.append(
                            DiffItem(
                                entity="choice",
                                identity=f"{doc.source_key}:s{season.number}:e{episode.number}:choices",
                                status="CHANGED",
                                details=(
                                    f"Episode {season.number}.{episode.number} has {len(existing_choices)} placeholder choices. "
                                    f"Safe replacement candidate: {len(parsed_choices)} real parsed choices."
                                ),
                            )
                        )
                    elif len(existing_choices) == 0:
                        choices_stat["NEW"] += len(parsed_choices)
                    else:
                        choices_stat["MATCH"] += min(len(existing_choices), len(parsed_choices))
                        if len(parsed_choices) > len(existing_choices):
                            choices_stat["NEW"] += len(parsed_choices) - len(existing_choices)
                else:
                    episodes_stat["NEW"] += 1
                    choices_stat["NEW"] += len(parsed_choices)
                    report.items.append(
                        DiffItem(
                            entity="episode",
                            identity=f"{doc.source_key}:s{season.number}:e{episode.number}",
                            status="NEW",
                            details=f"Episode {season.number}.{episode.number} '{episode.title}' is NEW ({len(parsed_choices)} choices)",
                        )
                    )

        report.seasons_summary = seasons_stat
        report.episodes_summary = episodes_stat
        report.choices_summary = choices_stat
        return report

    finally:
        conn.close()


def run_dry_run(url: str, raw_dir: Path = DEFAULT_RAW_DIR, prod_db_path: Path = DEFAULT_PROD_DB_PATH) -> dict[str, Any]:
    """Execute complete dry-run pipeline for a story URL.

    parse -> validate -> compare -> report
    Zero writes to SQLite.
    """
    # 1. Parse
    doc = parse_story_from_url(url, raw_dir=raw_dir)
    # 2. Validate
    val = validate_story_document(doc)
    # 3. Summarize
    summary = parser_summary(doc)
    # 4. Content Hash
    page_urls = doc.metadata.get("page_urls", [url])
    content_hash = compute_story_content_hash(page_urls, raw_dir=raw_dir)
    # 5. Diff with production DB
    diff = diff_story_with_production(doc, prod_db_path=prod_db_path)

    return {
        "status": "OK" if val.ok else "VALIDATION_FAILED",
        "story": {
            "title": doc.source_title,
            "source_key": doc.source_key,
            "canonical_url": doc.canonical_url,
            "parser_version": doc.parser_version,
            "content_hash": content_hash,
            "page_urls_count": len(page_urls),
        },
        "metrics": summary,
        "validation": {
            "ok": val.ok,
            "warnings_count": len(val.warnings),
            "errors_count": len(val.errors),
        },
        "diff": {
            "story_status": diff.story_status,
            "seasons": diff.seasons_summary,
            "episodes": diff.episodes_summary,
            "choices": diff.choices_summary,
        },
        "warnings": doc.warnings,
        "errors": doc.errors,
    }


def format_dry_run_report(dry_run_data: dict[str, Any]) -> str:
    """Format dry run results as human-readable markdown report."""
    st = dry_run_data["story"]
    met = dry_run_data["metrics"]
    diff = dry_run_data["diff"]
    val = dry_run_data["validation"]

    lines = [
        f"# Dry-Run Report: {st['title']}",
        f"- **Source key**: `{st['source_key']}`",
        f"- **Canonical URL**: {st['canonical_url']}",
        f"- **Parser version**: `{st['parser_version']}`",
        f"- **Content hash**: `{st['content_hash'][:16]}...`",
        f"- **Validation**: {'✅ OK' if val['ok'] else '❌ FAIL'}",
        "",
        "## Parsed Metrics",
        f"- Seasons: {met['seasons']}",
        f"- Episodes: {met['episodes']}",
        f"- Total Blocks: {met['blocks']}",
        f"- Total Choices: {met['choices']}",
        f"- Diamond Choices: {met['diamond_choices']}",
        f"- Parameter Effects: {met['parameter_effects']}",
        f"- Character Effects: {met['character_effects']}",
        f"- Future Effects: {met['future_effects']}",
        f"- Critical: {met['critical']}",
        f"- Unknown Blocks: {met['unknown_blocks']}",
        "",
        "## Production DB Diff (Read-Only)",
        f"- **Story status**: `{diff['story_status']}`",
        f"- **Seasons**: MATCH={diff['seasons'].get('MATCH', 0)}, NEW={diff['seasons'].get('NEW', 0)}",
        f"- **Episodes**: MATCH={diff['episodes'].get('MATCH', 0)}, NEW={diff['episodes'].get('NEW', 0)}",
        f"- **Choices**: MATCH={diff['choices'].get('MATCH', 0)}, NEW={diff['choices'].get('NEW', 0)}, PLACEHOLDER_REPLACE={diff['choices'].get('PLACEHOLDER_REPLACE', 0)}",
        "",
        f"- Warnings: {len(dry_run_data['warnings'])}",
        f"- Errors: {len(dry_run_data['errors'])}",
    ]
    return "\n".join(lines)


# ==============================================================================
# BATCH STAGING & FULL AUDIT PIPELINE (PHASE 8)
# ==============================================================================

@dataclass
class BatchSourceRecord:
    source_key: str
    canonical_url: str
    source_title: str
    status: str  # "SUCCESS" | "UP_TO_DATE" | "FAILED_PARSE" | "FAILED_VALIDATION" | "FAILED_LOSS_DETECTION"
    seasons: int = 0
    episodes: int = 0
    choices: int = 0
    diamond_choices: int = 0
    parameter_effects: int = 0
    character_effects: int = 0
    future_effects: int = 0
    critical: int = 0
    unknown_blocks: int = 0
    multi_option_blocks: int = 0
    multi_param_choices: int = 0
    warnings_count: int = 0
    errors_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    time_seconds: float = 0.0
    error_details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchStagingReport:
    total_sources: int
    success_count: int
    up_to_date_count: int
    failed_count: int
    total_time_seconds: float
    aggregate_metrics: dict[str, int]
    sources: list[BatchSourceRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_batch_staging(
    sources_path: Path = DEFAULT_DISCOVERED_SOURCES_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    staging_db_path: Path = DEFAULT_STAGING_DB_PATH,
    force: bool = False,
    delay_between: float = 0.1,
    progress_callback: Any = None,
) -> BatchStagingReport:
    """Process all discovered sources through parse -> validate -> stage pipeline.

    Guarantees:
    - Error isolation: one failed source never breaks the batch.
    - Zero writes to production DB.
    - Idempotent import into staging DB.
    """
    if not sources_path.exists():
        raise FileNotFoundError(f"Discovered sources file not found: {sources_path}")

    data = json.loads(sources_path.read_text(encoding="utf-8"))
    sources = data.get("sources", [])

    staging_db = StagingDatabase(db_path=staging_db_path)
    records: list[BatchSourceRecord] = []
    start_total_time = time.time()

    for idx, s in enumerate(sources, start=1):
        url = s["canonical_url"]
        key = s["source_key"]
        title = s.get("source_title") or s.get("title", "Unknown")
        t0 = time.time()

        if progress_callback:
            progress_callback(idx, len(sources), key, title)

        try:
            doc = parse_story_from_url(url, raw_dir=raw_dir, parsed_dir=parsed_dir)
            val = validate_story_document(doc)
            summary = parser_summary(doc)

            # Count multi-options
            multi_opt = 0
            multi_param = 0
            for season in doc.seasons:
                for ep in season.episodes:
                    for b in ep.blocks:
                        if b.choice:
                            if b.choice.text.startswith("—"):
                                multi_opt += 1
                            if len(b.choice.parameter_changes) > 1:
                                multi_param += 1

            page_urls = doc.metadata.get("page_urls", [url])
            content_hash = compute_story_content_hash(page_urls, raw_dir=raw_dir)

            if not val.ok:
                rec_status = "FAILED_VALIDATION"
            else:
                import_res = staging_db.import_story(doc, content_hash=content_hash, force=force)
                rec_status = "UP_TO_DATE" if import_res["status"] == "UP_TO_DATE" else "SUCCESS"

            dt = time.time() - t0
            rec = BatchSourceRecord(
                source_key=key,
                canonical_url=url,
                source_title=doc.source_title or title,
                status=rec_status,
                seasons=summary["seasons"],
                episodes=summary["episodes"],
                choices=summary["choices"],
                diamond_choices=summary["diamond_choices"],
                parameter_effects=summary["parameter_effects"],
                character_effects=summary["character_effects"],
                future_effects=summary["future_effects"],
                critical=summary["critical"],
                unknown_blocks=summary["unknown_blocks"],
                multi_option_blocks=multi_opt,
                multi_param_choices=multi_param,
                warnings_count=len(doc.warnings),
                errors_count=len(doc.errors),
                warnings=list(doc.warnings),
                errors=list(doc.errors),
                time_seconds=round(dt, 2),
            )
            records.append(rec)

        except Exception as exc:
            dt = time.time() - t0
            rec = BatchSourceRecord(
                source_key=key,
                canonical_url=url,
                source_title=title,
                status="FAILED_PARSE",
                errors_count=1,
                errors=[str(exc)],
                error_details=traceback.format_exc(),
                time_seconds=round(dt, 2),
            )
            records.append(rec)

        if delay_between > 0:
            time.sleep(delay_between)

    total_time = round(time.time() - start_total_time, 2)
    success_cnt = sum(1 for r in records if r.status == "SUCCESS")
    up_to_date_cnt = sum(1 for r in records if r.status == "UP_TO_DATE")
    failed_cnt = sum(1 for r in records if r.status.startswith("FAILED"))

    agg = {
        "stories": sum(1 for r in records if r.status in ("SUCCESS", "UP_TO_DATE")),
        "seasons": sum(r.seasons for r in records),
        "episodes": sum(r.episodes for r in records),
        "choices": sum(r.choices for r in records),
        "diamond_choices": sum(r.diamond_choices for r in records),
        "parameter_effects": sum(r.parameter_effects for r in records),
        "character_effects": sum(r.character_effects for r in records),
        "future_effects": sum(r.future_effects for r in records),
        "critical": sum(r.critical for r in records),
        "unknown_blocks": sum(r.unknown_blocks for r in records),
        "multi_option_blocks": sum(r.multi_option_blocks for r in records),
        "multi_param_choices": sum(r.multi_param_choices for r in records),
        "total_warnings": sum(r.warnings_count for r in records),
        "total_errors": sum(r.errors_count for r in records),
    }

    return BatchStagingReport(
        total_sources=len(sources),
        success_count=success_cnt,
        up_to_date_count=up_to_date_cnt,
        failed_count=failed_cnt,
        total_time_seconds=total_time,
        aggregate_metrics=agg,
        sources=records,
    )


@dataclass
class FullDiffSummary:
    total_staging_sources: int
    total_prod_stories: int
    matched_stories: int
    new_stories: int
    changed_stories: int
    unresolved_prod_stories: int
    aggregate_seasons: dict[str, int]
    aggregate_episodes: dict[str, int]
    aggregate_choices: dict[str, int]
    story_diffs: list[DiffReport] = field(default_factory=list)
    unresolved_stories: list[dict[str, Any]] = field(default_factory=list)
    placeholder_audit: dict[str, int] = field(default_factory=dict)


def run_full_production_diff(
    batch_report: BatchStagingReport,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    prod_db_path: Path = DEFAULT_PROD_DB_PATH,
) -> FullDiffSummary:
    """Execute complete read-only diff across all staging sources vs production DB."""
    conn = sqlite3.connect(f"file:{Path(prod_db_path).resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, title, slug, guide_source_name, guide_source_url FROM stories ORDER BY id")
    all_prod_stories = [dict(r) for r in cur.fetchall()]

    # Collect total placeholders in production DB
    cur.execute("SELECT count(*) FROM choices WHERE text LIKE '%Краткий пункт выбора%' OR tags LIKE '%gamesisart_import%'")
    total_placeholders_in_prod = cur.fetchone()[0]

    story_diffs: list[DiffReport] = []
    matched_prod_story_ids: set[int] = set()

    agg_seasons = {"MATCH": 0, "NEW": 0, "CHANGED": 0}
    agg_episodes = {"MATCH": 0, "NEW": 0, "CHANGED": 0}
    agg_choices = {"MATCH": 0, "NEW": 0, "CHANGED": 0, "PLACEHOLDER_REPLACE": 0}

    for rec in batch_report.sources:
        if rec.status.startswith("FAILED"):
            continue
        key_stem = rec.source_key.split(":", 1)[-1]
        json_path = parsed_dir / f"{key_stem}.json"
        if not json_path.exists():
            continue
        doc_data = json.loads(json_path.read_text(encoding="utf-8"))
        doc = StoryDocument.from_dict(doc_data)

        diff = diff_story_with_production(doc, prod_db_path=prod_db_path)
        story_diffs.append(diff)

        for s_status, count in diff.seasons_summary.items():
            agg_seasons[s_status] = agg_seasons.get(s_status, 0) + count
        for e_status, count in diff.episodes_summary.items():
            agg_episodes[e_status] = agg_episodes.get(e_status, 0) + count
        for c_status, count in diff.choices_summary.items():
            agg_choices[c_status] = agg_choices.get(c_status, 0) + count

        for it in diff.items:
            if it.entity == "story" and it.existing_id is not None:
                matched_prod_story_ids.add(it.existing_id)

    conn.close()

    matched_stories_cnt = len(matched_prod_story_ids)
    new_stories_cnt = sum(1 for d in story_diffs if d.story_status == "NEW")
    changed_stories_cnt = sum(
        1 for d in story_diffs if any(it.entity == "story" and it.status == "CHANGED" for it in d.items)
    )

    unresolved_stories = [
        s for s in all_prod_stories if s["id"] not in matched_prod_story_ids
    ]

    safe_replace_count = agg_choices.get("PLACEHOLDER_REPLACE", 0)
    needs_review_count = total_placeholders_in_prod - safe_replace_count

    return FullDiffSummary(
        total_staging_sources=len(story_diffs),
        total_prod_stories=len(all_prod_stories),
        matched_stories=matched_stories_cnt,
        new_stories=new_stories_cnt,
        changed_stories=changed_stories_cnt,
        unresolved_prod_stories=len(unresolved_stories),
        aggregate_seasons=agg_seasons,
        aggregate_episodes=agg_episodes,
        aggregate_choices=agg_choices,
        story_diffs=story_diffs,
        unresolved_stories=unresolved_stories,
        placeholder_audit={
            "total_placeholders": total_placeholders_in_prod,
            "safe_to_replace": safe_replace_count,
            "needs_review": needs_review_count,
        },
    )
