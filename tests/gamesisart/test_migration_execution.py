import shutil
import sqlite3
from pathlib import Path

import pytest

from scripts.gamesisart.migration import ProductionMigrator, compute_file_sha256

def get_pre_migration_db() -> Path:
    backups = sorted(Path(".").glob("club_romance_before_gamesisart_migration_*.db"))
    if backups:
        return backups[-1]
    return Path("club_romance.db")

PROD_DB_PATH = get_pre_migration_db()
STAGING_DB_PATH = Path("data/gamesisart/staging.db")


def test_production_migrator_on_temp_db(tmp_path: Path) -> None:
    """Execute complete migration pipeline on an isolated temporary database copy."""
    if not PROD_DB_PATH.exists() or not STAGING_DB_PATH.exists():
        pytest.skip("Required databases not found")

    temp_prod = tmp_path / "club_romance_temp.db"
    shutil.copy2(PROD_DB_PATH, temp_prod)

    temp_backup = tmp_path / "backup_test.db"

    migrator = ProductionMigrator(prod_db_path=temp_prod, staging_db_path=STAGING_DB_PATH)

    # 1. Test backup creation
    backup_file = migrator.create_verified_backup(backup_path=temp_backup)
    assert backup_file.exists()
    assert migrator.stats.backup_size == PROD_DB_PATH.stat().st_size
    assert migrator.stats.backup_integrity == "ok"
    backup_sha = migrator.stats.backup_sha256

    # 2. Run migration
    stats = migrator.run_migration()
    assert stats.committed is True
    assert stats.rollback_occurred is False
    assert stats.stories_updated_url == 49  # 42 exact + 7 alias
    assert stats.stories_created == 10
    assert stats.seasons_created == 90     # 76 in exact + 14 in new
    assert stats.episodes_created == 1036  # 874 in exact + 162 in new
    assert stats.choices_updated_inplace == 6279
    assert stats.choices_inserted_existing_episodes == 11440
    assert stats.choices_inserted_new_episodes == 35676  # 29607 + 453 + 5616
    assert stats.total_choices_inserted == 47116

    # Verify counts
    assert stats.post_stories == 64
    assert stats.post_seasons == 150
    assert stats.post_episodes == 1671
    assert stats.post_choices == 55351

    # User data integrity
    assert stats.post_progress == 6
    assert stats.post_subscriptions == 1
    assert stats.post_characters == 2

    # 3. Verify post-commit read-only verification
    post_verif = migrator.verify_post_commit()
    assert post_verif["integrity_check"] == "ok"
    assert post_verif["foreign_key_violations"] == 0
    assert post_verif["backup_intact"] is True
    assert post_verif["backup_sha256"] == backup_sha


def test_production_migrator_rollback_on_error(tmp_path: Path) -> None:
    """Verify migrator triggers clean rollback when an error occurs."""
    temp_prod = tmp_path / "club_romance_fail.db"
    shutil.copy2(PROD_DB_PATH, temp_prod)

    # Corrupt temp DB to trigger an error or use an invalid staging path
    migrator = ProductionMigrator(prod_db_path=temp_prod, staging_db_path=Path("non_existent.db"))

    with pytest.raises(Exception):
        migrator.run_migration()

    assert migrator.stats.rollback_occurred is True
    assert migrator.stats.committed is False
