from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.gamesisart import discovery
from scripts.gamesisart.parser import iter_blocks, parse_story_from_url, parser_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GamesIsArt tooling.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover_parser = subparsers.add_parser("discover", help="Discover Romance Club story guide pages.")
    discover_parser.add_argument("--catalog-url", default=discovery.CATALOG_URL)
    discover_parser.add_argument("--output", type=Path, default=discovery.DEFAULT_OUTPUT_PATH)
    discover_parser.add_argument("--report", type=Path, default=discovery.DEFAULT_REPORT_PATH)
    discover_parser.add_argument("--database", type=Path, default=discovery.DEFAULT_DATABASE_PATH)
    discover_parser.add_argument("--timeout", type=float, default=20.0)
    discover_parser.add_argument("--retries", type=int, default=2)
    discover_parser.add_argument("--delay", type=float, default=0.5)
    parse_parser = subparsers.add_parser("parse", help="Parse one GamesIsArt story source into JSON.")
    parse_parser.add_argument("--url", required=True)
    parse_parser.add_argument("--raw-dir", type=Path, default=Path("data/gamesisart/raw"))
    parse_parser.add_argument("--parsed-dir", type=Path, default=Path("data/gamesisart/parsed"))
    parse_parser.add_argument("--overwrite-raw", action="store_true")

    dry_run_parser = subparsers.add_parser("dry-run", help="Run dry-run pipeline (parse, validate, diff) with zero SQLite writes.")
    dry_run_parser.add_argument("--url", required=True)
    dry_run_parser.add_argument("--raw-dir", type=Path, default=Path("data/gamesisart/raw"))
    dry_run_parser.add_argument("--prod-db", type=Path, default=Path("club_romance.db"))

    diff_parser = subparsers.add_parser("diff", help="Compare parsed story with existing production SQLite database.")
    diff_parser.add_argument("--url", required=True)
    diff_parser.add_argument("--raw-dir", type=Path, default=Path("data/gamesisart/raw"))
    diff_parser.add_argument("--prod-db", type=Path, default=Path("club_romance.db"))

    stage_parser = subparsers.add_parser("stage", help="Idempotently import parsed story into staging SQLite database (data/gamesisart/staging.db).")
    stage_parser.add_argument("--url", required=True)
    stage_parser.add_argument("--raw-dir", type=Path, default=Path("data/gamesisart/raw"))
    stage_parser.add_argument("--staging-db", type=Path, default=Path("data/gamesisart/staging.db"))
    stage_parser.add_argument("--force", action="store_true")

    stage_all_parser = subparsers.add_parser("stage-all", help="Process all 59 discovered sources into staging database.")
    stage_all_parser.add_argument("--sources", type=Path, default=Path("data/gamesisart/discovered_sources.json"))
    stage_all_parser.add_argument("--raw-dir", type=Path, default=Path("data/gamesisart/raw"))
    stage_all_parser.add_argument("--parsed-dir", type=Path, default=Path("data/gamesisart/parsed"))
    stage_all_parser.add_argument("--staging-db", type=Path, default=Path("data/gamesisart/staging.db"))
    stage_all_parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = build_parser().parse_args(argv)
    if args.command == "discover":
        result = discovery.discover(
            catalog_url=args.catalog_url,
            output_path=args.output,
            report_path=args.report,
            database_path=args.database,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
        )
        print(f"Discovered sources: {len(result.sources)}")
        print(f"Unique canonical URLs: {result.stats.get('canonical_urls', 0)}")
        print(f"Duplicate URLs: {result.stats.get('duplicate_urls', 0)}")
        print(f"Filtered links: {result.stats.get('filtered_links', 0)}")
        print(f"Conflicts: {len(result.conflicts)}")
        print(f"Existing DB matches: {result.stats.get('existing_db_matches', 0)}")
        print(f"Potential duplicates: {result.stats.get('potential_duplicates', 0)}")
        print(f"JSON: {args.output}")
        print(f"Report: {args.report}")
        return 0 if not result.conflicts else 2
    if args.command == "parse":
        document = parse_story_from_url(
            args.url,
            raw_dir=args.raw_dir,
            parsed_dir=args.parsed_dir,
            overwrite_raw=args.overwrite_raw,
        )
        summary = parser_summary(document)
        print("=" * 40)
        print("GamesIsArt Parser Preview")
        print("Story:")
        print(document.source_title)
        print()
        print("Source:")
        print(document.source_url)
        print()
        print(f"Seasons:\n{summary['seasons']}")
        for season in document.seasons:
            print(f"Season {season.number}:")
            print(f"title: {season.title}")
            print(f"episodes: {len(season.episodes)}")
            for episode in season.episodes:
                print(f"Episode {episode.number} — {episode.title}")
        print(f"Total episodes:\n{summary['episodes']}")
        print(f"Total blocks:\n{summary['blocks']}")
        print(f"Choices:\n{summary['choices']}")
        print(f"Diamond choices:\n{summary['diamond_choices']}")
        print(f"Parameter effects:\n{summary['parameter_effects']}")
        print(f"Character effects:\n{summary['character_effects']}")
        print(f"Future effects:\n{summary['future_effects']}")
        print(f"Critical:\n{summary['critical']}")
        print(f"Unknown blocks:\n{summary['unknown_blocks']}")
        print(f"Warnings:\n{summary['warnings']}")
        print(f"Errors:\n{summary['errors']}")
        print("=" * 40)
        print("Choice samples:")
        shown = 0
        for season, episode, block in iter_blocks(document):
            if not block.choice:
                continue
            choice = block.choice
            print(
                f"{season.number}.{episode.number} | block {block.order} | {choice.text} | "
                f"cost={choice.cost_diamonds} | tags={','.join(choice.tags) or '-'} | "
                f"parameters={'; '.join(choice.parameter_changes) or '-'} | "
                f"characters={'; '.join(choice.character_effects) or '-'} | "
                f"future={'; '.join(choice.future_effects) or '-'} | critical={choice.is_critical}"
            )
            shown += 1
            if shown >= 10:
                break
        return 0 if not document.errors else 2

    if args.command == "dry-run":
        from scripts.gamesisart.staging import format_dry_run_report, run_dry_run
        data = run_dry_run(args.url, raw_dir=args.raw_dir, prod_db_path=args.prod_db)
        print(format_dry_run_report(data))
        return 0 if data["status"] == "OK" else 2

    if args.command == "diff":
        from scripts.gamesisart.parser import parse_story_from_url
        from scripts.gamesisart.staging import diff_story_with_production
        doc = parse_story_from_url(args.url, raw_dir=args.raw_dir)
        report = diff_story_with_production(doc, prod_db_path=args.prod_db)
        print(f"Diff Report for {report.story_title}:")
        print(f"  Story Status: {report.story_status}")
        print(f"  Seasons: {report.seasons_summary}")
        print(f"  Episodes: {report.episodes_summary}")
        print(f"  Choices: {report.choices_summary}")
        print("  Key items:")
        for it in report.items[:15]:
            print(f"    [{it.entity.upper()}] {it.identity} -> {it.status}: {it.details}")
        if len(report.items) > 15:
            print(f"    ... and {len(report.items) - 15} more items.")
        return 0

    if args.command == "stage":
        from scripts.gamesisart.parser import parse_story_from_url
        from scripts.gamesisart.staging import StagingDatabase
        doc = parse_story_from_url(args.url, raw_dir=args.raw_dir)
        st_db = StagingDatabase(db_path=args.staging_db)
        result = st_db.import_story(doc, force=args.force)
        print("Staging Import Result:")
        print(f"  Status: {result['status']}")
        print(f"  Source: {result['source_key']}")
        print(f"  Content Hash: {result.get('content_hash', '')[:16]}...")
        print(f"  Seasons: {result['seasons']}, Episodes: {result['episodes']}, Choices: {result['choices']}")
        return 0

    if args.command == "stage-all":
        from scripts.gamesisart.staging import run_batch_staging

        def progress(idx, total, key, title):
            print(f"[{idx}/{total}] Processing: {title} ({key})...", flush=True)

        report = run_batch_staging(
            sources_path=args.sources,
            raw_dir=args.raw_dir,
            parsed_dir=args.parsed_dir,
            staging_db_path=args.staging_db,
            force=args.force,
            progress_callback=progress,
        )
        print("\n" + "=" * 50)
        print("BATCH STAGING COMPLETE")
        print("=" * 50)
        print(f"Total Sources: {report.total_sources}")
        print(f"Success: {report.success_count}")
        print(f"Up-to-Date: {report.up_to_date_count}")
        print(f"Failed: {report.failed_count}")
        print(f"Total Time: {report.total_time_seconds}s")
        print("\nAggregate Metrics:")
        for k, v in report.aggregate_metrics.items():
            print(f"  {k}: {v}")
        return 0 if report.failed_count == 0 else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
