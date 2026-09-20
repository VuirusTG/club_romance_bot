import asyncio
import json
from pathlib import Path

from scripts.backup_db import backup_database
from scripts.preflight_check import (
    check_python_version,
    check_dependencies,
    check_database,
)
from bot.main import handle_root, handle_health


def test_preflight_core_checks():
    assert check_python_version() is True
    assert check_dependencies() is True
    assert check_database() is True


def test_hot_backup(tmp_path):
    backup_file = backup_database(
        source_db=Path("club_romance.db"),
        backup_dir=tmp_path / "backups",
        keep_count=2,
    )
    assert backup_file.exists()
    assert backup_file.stat().st_size > 10 * 1024 * 1024


def test_health_check_endpoints():
    class DummyRequest:
        pass

    req = DummyRequest()
    root_resp = asyncio.run(handle_root(req))
    assert root_resp.status == 200
    assert "Клуб Романтики" in root_resp.text

    health_resp = asyncio.run(handle_health(req))
    assert health_resp.status == 200
    data = json.loads(health_resp.text)
    assert data["status"] == "healthy"
    assert data["stories"] == 58
    assert data["choices"] == 53236
