#!/usr/bin/env python3
"""MIRAGE Database Migration Preflight Verification Script.

Executes pre-deployment validation for PostgreSQL database connectivity,
Alembic migration graph consistency, schema head status, and unprivileged role
fencing prior to application container dispatch.

Usage:
    python scripts/migration_preflight.py [--check-only] [--json] [--database-url <url>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def get_alembic_script_directory(alembic_ini_path: str = "alembic.ini") -> tuple[Config, ScriptDirectory]:
    """Load Alembic script directory from configuration file."""
    if not os.path.exists(alembic_ini_path):
        raise FileNotFoundError(f"Alembic configuration file '{alembic_ini_path}' not found")
    alembic_cfg = Config(alembic_ini_path)
    script_dir = ScriptDirectory.from_config(alembic_cfg)
    return alembic_cfg, script_dir


def check_database_migration_status(
    database_url: str | None = None,
    alembic_ini_path: str = "alembic.ini",
) -> dict[str, Any]:
    """Perform preflight checks against the database and migration graph."""
    # 1. Resolve database URL
    sync_url = database_url or os.getenv("DATABASE_SYNC_URL")
    if not sync_url:
        async_url = os.getenv("DATABASE_URL", "")
        if "postgresql+asyncpg://" in async_url:
            sync_url = async_url.replace("postgresql+asyncpg://", "postgresql://")
        elif "sqlite+aiosqlite://" in async_url:
            sync_url = async_url.replace("sqlite+aiosqlite://", "sqlite://")
        else:
            sync_url = async_url

    if not sync_url:
        sync_url = "postgresql+psycopg2://mirage:mirage_dev_secret@localhost:5432/mirage_db"
    elif sync_url.startswith("postgresql://"):
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    # Sanitize URL for report display (mask password)
    safe_url = sync_url
    if "@" in safe_url and "://" in safe_url:
        proto, rest = safe_url.split("://", 1)
        creds, host_part = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        safe_url = f"{proto}://{user}:***@{host_part}"

    report: dict[str, Any] = {
        "database_url": safe_url,
        "connected": False,
        "is_postgres": False,
        "alembic_version_table_exists": False,
        "current_db_revision": None,
        "target_head_revision": None,
        "status": "UNKNOWN",
        "pending_revisions": [],
        "role_checks": {},
        "errors": [],
    }

    # 2. Inspect Alembic Script Directory
    try:
        _cfg, script_dir = get_alembic_script_directory(alembic_ini_path)
        heads = script_dir.get_heads()
        if len(heads) == 0:
            report["errors"].append("No migration heads found in repository")
            report["status"] = "ERROR_NO_HEADS"
            return report
        if len(heads) > 1:
            report["errors"].append(f"Multiple migration heads detected (branching violation): {heads}")
            report["status"] = "ERROR_MULTIPLE_HEADS"
            return report
        report["target_head_revision"] = heads[0]
    except Exception as exc:
        report["errors"].append(f"Failed loading Alembic migration graph: {exc}")
        report["status"] = "ERROR_ALEMBIC_CONFIG"
        return report

    # 3. Test Database Connectivity
    try:
        engine = create_engine(sync_url, pool_pre_ping=True)
        with engine.connect() as conn:
            report["connected"] = True
            is_postgres = conn.dialect.name == "postgresql"
            report["is_postgres"] = is_postgres

            # Check if alembic_version table exists
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            if "alembic_version" in tables:
                report["alembic_version_table_exists"] = True
                res = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
                if res:
                    report["current_db_revision"] = res[0][0]

            # Role security check for PostgreSQL
            if is_postgres:
                # Check current connected user
                current_user = conn.execute(text("SELECT current_user, session_user;")).fetchone()
                if current_user:
                    report["role_checks"]["connected_user"] = current_user[0]

                # Check mirage_app unprivileged role properties if it exists
                app_role_res = conn.execute(
                    text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'mirage_app';")
                ).fetchone()
                if app_role_res:
                    report["role_checks"]["mirage_app_exists"] = True
                    report["role_checks"]["mirage_app_nosuperuser"] = not bool(app_role_res[1])
                    report["role_checks"]["mirage_app_nobypassrls"] = not bool(app_role_res[2])
                else:
                    report["role_checks"]["mirage_app_exists"] = False

    except Exception as exc:
        report["errors"].append(f"Database connection failed: {exc}")
        report["status"] = "CONNECTION_FAILED"
        return report

    # 4. Determine Migration Status
    current_rev = report["current_db_revision"]
    target_head = report["target_head_revision"]

    if current_rev is None:
        report["status"] = "FRESH_DATABASE_PENDING_MIGRATION"
        # All revisions up to target_head are pending
        all_revs = [s.revision for s in script_dir.walk_revisions()]
        report["pending_revisions"] = list(reversed(all_revs))
    elif current_rev == target_head:
        report["status"] = "UP_TO_DATE"
        report["pending_revisions"] = []
    else:
        # Check if current_rev is an ancestor of target_head
        try:
            pending: list[str] = []
            for sc in script_dir.iterate_revisions(target_head, current_rev):
                if sc.revision != current_rev:
                    pending.append(sc.revision)
            report["pending_revisions"] = list(reversed(pending))
            report["status"] = "MIGRATIONS_PENDING"
        except Exception:
            report["status"] = "DIVERGENT_OR_UNKNOWN_REVISION"
            report["errors"].append(f"Current revision '{current_rev}' is not an ancestor of head '{target_head}'")

    return report


def main() -> int:
    """CLI entrypoint for migration preflight."""
    parser = argparse.ArgumentParser(description="MIRAGE Database Migration Preflight Verification")
    parser.add_argument("--database-url", type=str, default=None, help="Database sync URL to inspect")
    parser.add_argument("--alembic-ini", type=str, default="alembic.ini", help="Path to alembic.ini")
    parser.add_argument("--check-only", action="store_true", help="Exit non-zero if pending or failed")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    args = parser.parse_args()

    report = check_database_migration_status(
        database_url=args.database_url,
        alembic_ini_path=args.alembic_ini,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 60)
        print("  MIRAGE Database Migration Preflight Audit")
        print("=" * 60)
        print(f"  Database URL:        {report['database_url']}")
        print(f"  Connected:           {'YES' if report['connected'] else 'NO'}")
        print(f"  Database Dialect:    {'PostgreSQL' if report['is_postgres'] else 'Other'}")
        print(f"  Current DB Revision: {report['current_db_revision'] or 'NONE (Fresh)'}")
        print(f"  Target Head Rev:     {report['target_head_revision']}")
        print(f"  Migration Status:    {report['status']}")
        if report["pending_revisions"]:
            print(f"  Pending Revisions:   {len(report['pending_revisions'])} revision(s)")
            for r in report["pending_revisions"]:
                print(f"    - {r}")
        if report["role_checks"]:
            print(f"  Role Checks:         {report['role_checks']}")
        if report["errors"]:
            print("  Errors:")
            for err in report["errors"]:
                print(f"    ! {err}")
        print("=" * 60)

    # Return exit codes
    if report["status"] == "UP_TO_DATE":
        return 0
    elif report["status"] in ("FRESH_DATABASE_PENDING_MIGRATION", "MIGRATIONS_PENDING"):
        return 2 if args.check_only else 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
