"""
Safe Online Hot Backup Script for Club Romance SQLite Database.

Uses the SQLite Backup API (conn.backup) to guarantee atomic, consistent
snapshots even while the bot is actively writing to the database.

Features:
- Online atomic backup without stopping the bot
- Verification via PRAGMA integrity_check
- SHA-256 calculation
- Automatic backup rotation (keeps latest N backups)
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def backup_database(
    source_db: Path = Path("club_romance.db"),
    backup_dir: Path = Path("backups"),
    keep_count: int = 10,
) -> Path:
    if not source_db.exists():
        raise FileNotFoundError(f"Source database {source_db} not found.")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = backup_dir / f"club_romance_backup_{timestamp}.db"

    print(f"[1/4] Connecting to source database '{source_db}'...")
    src_conn = sqlite3.connect(source_db)
    dst_conn = sqlite3.connect(target_path)

    print(f"[2/4] Performing online atomic backup to '{target_path}'...")
    with dst_conn:
        src_conn.backup(dst_conn, pages=100)
    src_conn.close()
    dst_conn.close()

    size_bytes = target_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    sha256 = compute_sha256(target_path)
    print(f"      Size: {size_mb:.2f} MB ({size_bytes} bytes) | SHA-256: {sha256}")

    print("[3/4] Verifying backup integrity...")
    verify_conn = sqlite3.connect(target_path)
    cur = verify_conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    res = cur.fetchone()[0]
    verify_conn.close()

    if res != "ok":
        target_path.unlink(missing_ok=True)
        raise RuntimeError(f"Backup verification failed: {res}")
    print("      Integrity check: OK")

    print(f"[4/4] Rotating backups (retaining up to {keep_count} latest copies)...")
    backups = sorted(backup_dir.glob("club_romance_backup_*.db"), key=lambda p: p.stat().st_mtime)
    if len(backups) > keep_count:
        for old in backups[:-keep_count]:
            print(f"      Removing old backup: {old.name}")
            old.unlink(missing_ok=True)

    print(f"[DONE] Backup completed successfully: {target_path}")
    return target_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create hot atomic backup of SQLite DB")
    parser.add_argument("--db", default="club_romance.db", type=Path, help="Path to source SQLite DB")
    parser.add_argument("--dir", default="backups", type=Path, help="Target backup directory")
    parser.add_argument("--keep", default=10, type=int, help="Number of backups to keep")
    args = parser.parse_args()

    try:
        backup_database(source_db=args.db, backup_dir=args.dir, keep_count=args.keep)
        return 0
    except Exception as e:
        print(f"[ERROR] Backup failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
