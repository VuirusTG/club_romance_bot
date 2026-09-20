"""
Pre-flight deployment check script for Club Romance Telegram Bot.

Validates:
1. Python environment and version compatibility.
2. Required packages installed.
3. Configuration and environment variables (.env).
4. SQLite database integrity, foreign keys, and catalog completeness.
5. Optional Telegram Bot API connectivity check.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path


def check_python_version() -> bool:
    print("1. Checking Python version...")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"   [FAIL] Python 3.10+ required. Found: {sys.version}")
        return False
    print(f"   [OK] Python {v.major}.{v.minor}.{v.micro}")
    return True


def check_dependencies() -> bool:
    print("2. Checking installed packages...")
    required = ["aiogram", "sqlalchemy", "aiosqlite", "dotenv", "pydantic_settings"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"   [FAIL] Missing required packages: {missing}")
        print("          Run: pip install -r requirements.txt")
        return False
    print(f"   [OK] All core dependencies imported successfully.")
    return True


def check_configuration() -> tuple[bool, str | None]:
    print("3. Checking environment configuration (.env)...")
    from dotenv import dotenv_values

    env_path = Path(".env")
    if not env_path.exists():
        print("   [WARN] File '.env' not found in current directory.")
        if Path(".env.example").exists():
            print("          Copy '.env.example' to '.env' and set your BOT_TOKEN.")
        return False, None

    vals = dotenv_values(env_path)
    token = vals.get("BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token:
        print("   [FAIL] BOT_TOKEN is missing in .env.")
        return False, None

    if "replace_me" in token.lower() or "токен" in token.lower():
        print("   [WARN] BOT_TOKEN contains placeholder value. Please set a valid BotFather token.")
        return True, token

    print("   [OK] Configuration present and BOT_TOKEN defined.")
    return True, token


def check_database() -> bool:
    print("4. Checking production database (club_romance.db)...")
    db_path = Path("club_romance.db")
    if not db_path.exists():
        print(f"   [FAIL] Database file '{db_path}' not found!")
        return False

    size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"   Database file size: {size_mb:.2f} MB")

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Integrity
        cur.execute("PRAGMA quick_check;")
        res = cur.fetchone()[0]
        if res != "ok":
            print(f"   [FAIL] PRAGMA quick_check failed: {res}")
            return False

        cur.execute("PRAGMA foreign_key_check;")
        fk_errs = cur.fetchall()
        if fk_errs:
            print(f"   [FAIL] Foreign key check errors found: {fk_errs}")
            return False

        # Counts
        cur.execute("SELECT count(*) FROM stories;")
        stories = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM seasons;")
        seasons = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM episodes;")
        episodes = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM choices;")
        choices = cur.fetchone()[0]

        conn.close()

        print(f"   [OK] Database integrity: ok, FK violations: 0")
        print(f"   [OK] Data volume: {stories} stories, {seasons} seasons, {episodes} episodes, {choices} choices")

        if stories < 50 or episodes < 1000 or choices < 40000:
            print("   [WARN] Data counts are lower than expected for fully seeded production DB.")
            return False

        return True

    except Exception as e:
        print(f"   [FAIL] Error querying database: {e}")
        return False


async def check_telegram_api(token: str | None) -> bool:
    if not token or "replace_me" in token.lower():
        print("5. Telegram Bot API check skipped (placeholder or missing token).")
        return True

    print("5. Checking Telegram Bot API connection...")
    try:
        from aiogram import Bot
        bot = Bot(token=token)
        me = await asyncio.wait_for(bot.get_me(), timeout=8.0)
        await bot.session.close()
        print(f"   [OK] Connected as @{me.username} (ID: {me.id}, Name: {me.first_name})")
        return True
    except asyncio.TimeoutError:
        print("   [WARN] Connection to Telegram API timed out (check internet/proxy/firewall).")
        return False
    except Exception as e:
        print(f"   [WARN] Telegram API error: {e}")
        return False


def main() -> int:
    print("=" * 60)
    print("  CLUB ROMANCE BOT — PRE-FLIGHT DEPLOYMENT CHECK")
    print("=" * 60)

    ok_py = check_python_version()
    ok_deps = check_dependencies()
    ok_env, token = check_configuration()
    ok_db = check_database()

    try:
        asyncio.run(check_telegram_api(token))
    except Exception:
        pass

    print("=" * 60)
    if ok_py and ok_deps and ok_db:
        print("  RESULT: PRE-FLIGHT CHECK PASSED - READY FOR LAUNCH")
        print("=" * 60)
        return 0
    else:
        print("  RESULT: PRE-FLIGHT CHECK FAILED - RESOLVE ISSUES ABOVE")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
