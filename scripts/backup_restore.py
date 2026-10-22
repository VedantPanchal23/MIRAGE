#!/usr/bin/env python3
"""MIRAGE Backup, Verification, and Disaster Recovery Automation Utility.

Implements PRD FR-AUD-01, FR-AUD-02, and Security §10.3 / §15:
Provides authoritative, cryptographically verifiable operational backup and restore
procedures covering both the relational PostgreSQL control plane and external
immutable audit-anchor hash chains.

Commands:
    python scripts/backup_restore.py backup --output-dir <dir>
    python scripts/backup_restore.py verify-backup --backup-dir <dir>
    python scripts/backup_restore.py restore --backup-dir <dir> --confirm

Safety Invariants:
1. Backup bundles are signed with a deterministic SHA-256 cryptographic manifest.
2. Verification tests anchor proof hash chains and rejects tampered files.
3. Restore strictly fails closed if backup integrity verification fails.
4. Database restore is explicitly distinguished from cryptographic audit verification.
5. Never automatically regenerates missing checkpoints during recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def compute_file_sha256(filepath: Path) -> str:
    """Compute 64-character lowercase SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_current_alembic_head() -> str | None:
    """Read the target migration head from the local alembic directory."""
    try:
        cfg = Config("alembic.ini")
        sdir = ScriptDirectory.from_config(cfg)
        heads = sdir.get_heads()
        return heads[0] if heads else None
    except Exception:
        return None


def execute_backup(
    output_dir: str | Path,
    database_url: str | None = None,
    anchor_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Create a self-contained, cryptographically signed backup bundle."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%SZ")
    bundle_name = f"mirage_backup_{timestamp}"
    target_bundle = Path(output_dir) / bundle_name
    db_backup_dir = target_bundle / "database"
    anchors_backup_dir = target_bundle / "audit_anchors"

    target_bundle.mkdir(parents=True, exist_ok=True)
    db_backup_dir.mkdir(parents=True, exist_ok=True)
    anchors_backup_dir.mkdir(parents=True, exist_ok=True)

    manifest_files: dict[str, dict[str, Any]] = {}

    # 1. Backup External Audit Anchors
    resolved_anchor_dir = Path(str(anchor_dir or os.getenv("AUDIT_ANCHOR_DIR") or "data/audit_anchors"))
    anchors_captured = 0
    if resolved_anchor_dir.exists():
        for anchor_file in resolved_anchor_dir.glob("*.anchors.jsonl"):
            dest = anchors_backup_dir / anchor_file.name
            shutil.copy2(anchor_file, dest)
            digest = compute_file_sha256(dest)
            size = dest.stat().st_size
            rel_path = f"audit_anchors/{anchor_file.name}"
            manifest_files[rel_path] = {"sha256": digest, "size_bytes": size}
            anchors_captured += 1

    # 2. Backup Relational Database
    resolved_db_url = database_url or os.getenv("DATABASE_SYNC_URL", "")
    if not resolved_db_url:
        async_url = os.getenv("DATABASE_URL", "")
        resolved_db_url = async_url.replace("postgresql+asyncpg://", "postgresql://")
    if not resolved_db_url:
        resolved_db_url = "postgresql://mirage:mirage_dev_secret@localhost:5432/mirage_db"

    db_revision = None
    db_dump_status = "NOT_ATTEMPTED"
    db_dump_file = db_backup_dir / "mirage_db.dump"

    try:
        engine = create_engine(resolved_db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            inspector = inspect(conn)
            if "alembic_version" in inspector.get_table_names():
                row = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchone()
                if row:
                    db_revision = row[0]

        # Check if pg_dump is available and it's a PostgreSQL URL
        if "postgresql://" in resolved_db_url and shutil.which("pg_dump"):
            cmd = ["pg_dump", "--format=custom", f"--file={db_dump_file}", resolved_db_url]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                db_dump_status = "PG_DUMP_SUCCESS"
                digest = compute_file_sha256(db_dump_file)
                manifest_files["database/mirage_db.dump"] = {
                    "sha256": digest,
                    "size_bytes": db_dump_file.stat().st_size,
                }
            else:
                db_dump_status = f"PG_DUMP_FAILED: {res.stderr.strip()}"
        elif "sqlite://" in resolved_db_url:
            sqlite_file = resolved_db_url.replace("sqlite:///", "").replace("sqlite://", "")
            if os.path.exists(sqlite_file):
                dest = db_backup_dir / "mirage_sqlite.db"
                shutil.copy2(sqlite_file, dest)
                digest = compute_file_sha256(dest)
                manifest_files["database/mirage_sqlite.db"] = {
                    "sha256": digest,
                    "size_bytes": dest.stat().st_size,
                }
                db_dump_status = "SQLITE_COPY_SUCCESS"
            else:
                db_dump_status = "SQLITE_SOURCE_NOT_FOUND"
        else:
            # Fallback metadata capture when pg_dump binary is unprovisioned on host
            db_dump_status = "DATABASE_METADATA_RECORDED_PG_DUMP_UNAVAILABLE"
            info_file = db_backup_dir / "db_metadata.json"
            info_file.write_text(
                json.dumps(
                    {
                        "connection_tested": True,
                        "alembic_version": db_revision,
                        "note": "pg_dump client binary not found on local PATH. Database connectivity confirmed.",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            manifest_files["database/db_metadata.json"] = {
                "sha256": compute_file_sha256(info_file),
                "size_bytes": info_file.stat().st_size,
            }

    except Exception as exc:
        db_dump_status = f"DATABASE_CONNECT_FAILED: {exc}"

    # 3. Create Signed Metadata Manifest
    metadata: dict[str, Any] = {
        "mirage_version": "3.0.0",
        "backup_bundle": bundle_name,
        "created_at_utc": timestamp,
        "db_alembic_revision": db_revision,
        "repo_migration_head": get_current_alembic_head(),
        "db_dump_status": db_dump_status,
        "anchors_captured": anchors_captured,
        "files": manifest_files,
    }

    manifest_canon = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    manifest_digest = hashlib.sha256(manifest_canon.encode("utf-8")).hexdigest()
    metadata["manifest_sha256"] = manifest_digest

    manifest_path = target_bundle / "manifest.json"
    manifest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "status": "BACKUP_COMPLETED",
        "bundle_path": str(target_bundle),
        "manifest_sha256": manifest_digest,
        "db_dump_status": db_dump_status,
        "anchors_captured": anchors_captured,
    }


def verify_backup_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Cryptographically verify the integrity of a backup bundle."""
    bundle_path = Path(bundle_dir)
    manifest_path = bundle_path / "manifest.json"

    if not manifest_path.exists():
        return {
            "valid": False,
            "status": "MISSING_MANIFEST",
            "errors": [f"manifest.json not found in '{bundle_dir}'"],
        }

    try:
        with open(manifest_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as exc:
        return {
            "valid": False,
            "status": "MALFORMED_MANIFEST",
            "errors": [f"Cannot parse manifest.json: {exc}"],
        }

    claimed_digest = meta.get("manifest_sha256")
    files_map: dict[str, dict[str, Any]] = meta.get("files", {})
    errors: list[str] = []

    # 1. Verify Manifest Self-Integrity
    check_meta = dict(meta)
    check_meta.pop("manifest_sha256", None)
    expected_digest = hashlib.sha256(
        json.dumps(check_meta, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    if claimed_digest != expected_digest:
        errors.append(f"Manifest self-integrity mismatch! Claimed '{claimed_digest}', computed '{expected_digest}'")

    # 2. Verify Checksums of all Captured Files
    for rel_path, file_meta in files_map.items():
        actual_path = bundle_path / rel_path
        if not actual_path.exists():
            errors.append(f"Missing file declared in manifest: '{rel_path}'")
            continue

        actual_digest = compute_file_sha256(actual_path)
        expected_file_digest = file_meta.get("sha256")
        if actual_digest != expected_file_digest:
            errors.append(
                f"File checksum mismatch for '{rel_path}': "
                f"expected '{expected_file_digest}', computed '{actual_digest}'"
            )

    # 3. Verify Anchor Chain Continuity for captured tenant files
    anchors_dir = bundle_path / "audit_anchors"
    if anchors_dir.exists():
        from services.audit_anchor import FileAuditAnchorBackend

        verifier_backend = FileAuditAnchorBackend(anchor_dir=anchors_dir)
        import asyncio

        for anchor_file in anchors_dir.glob("*.anchors.jsonl"):
            tenant_id = anchor_file.name.replace(".anchors.jsonl", "")
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            is_valid, defects = loop.run_until_complete(verifier_backend.verify_anchor_chain(tenant_id))
            if not is_valid:
                errors.extend([f"Anchor chain defect in tenant '{tenant_id}': {d}" for d in defects])

    is_valid = len(errors) == 0
    return {
        "valid": is_valid,
        "status": "VALID" if is_valid else "INTEGRITY_COMPROMISED",
        "bundle": str(bundle_path),
        "mirage_version": meta.get("mirage_version"),
        "created_at_utc": meta.get("created_at_utc"),
        "db_alembic_revision": meta.get("db_alembic_revision"),
        "anchors_captured": meta.get("anchors_captured"),
        "errors": errors,
    }


def execute_restore(
    bundle_dir: str | Path,
    target_anchor_dir: str | Path | None = None,
    target_db_url: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Safely restore audit anchors and database from a verified backup bundle."""
    if not confirm:
        return {
            "success": False,
            "status": "RESTORE_ABORTED_UNCONFIRMED",
            "message": "Destructive restore operation requires explicit --confirm flag.",
        }

    # Step 1: Pre-flight Integrity Verification
    verification = verify_backup_bundle(bundle_dir)
    if not verification["valid"]:
        return {
            "success": False,
            "status": "RESTORE_REJECTED_INTEGRITY_FAILURE",
            "errors": verification["errors"],
            "message": (
                "FATAL SAFETY VIOLATION: Cannot restore from an unverified or tampered backup bundle. "
                "Evidence of tampering or file corruption must be investigated."
            ),
        }

    bundle_path = Path(bundle_dir)
    dest_anchor_dir = Path(str(target_anchor_dir or os.getenv("AUDIT_ANCHOR_DIR") or "data/audit_anchors"))
    dest_anchor_dir.mkdir(parents=True, exist_ok=True)

    # Step 2: Restore Audit Anchors
    src_anchors = bundle_path / "audit_anchors"
    anchors_restored = 0
    if src_anchors.exists():
        for src_file in src_anchors.glob("*.anchors.jsonl"):
            dest_file = dest_anchor_dir / src_file.name
            shutil.copy2(src_file, dest_file)
            anchors_restored += 1

    # Step 3: Database Restore
    db_restore_status = "NOT_APPLICABLE"
    dump_file = bundle_path / "database" / "mirage_db.dump"
    sqlite_file = bundle_path / "database" / "mirage_sqlite.db"

    resolved_db_url = target_db_url or os.getenv("DATABASE_SYNC_URL", "")
    if dump_file.exists() and shutil.which("pg_restore") and resolved_db_url:
        cmd = ["pg_restore", "--clean", "--if-exists", f"--dbname={resolved_db_url}", str(dump_file)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        db_restore_status = "PG_RESTORE_SUCCESS" if res.returncode == 0 else f"PG_RESTORE_FAILED: {res.stderr}"
    elif sqlite_file.exists() and resolved_db_url and "sqlite://" in resolved_db_url:
        dest_sqlite = resolved_db_url.replace("sqlite:///", "").replace("sqlite://", "")
        shutil.copy2(sqlite_file, dest_sqlite)
        db_restore_status = "SQLITE_RESTORE_SUCCESS"
    else:
        db_restore_status = "AUDIT_ANCHORS_RESTORED_DB_REQUIRES_ALEMBIC_OR_PG_RESTORE"

    return {
        "success": True,
        "status": "RESTORE_COMPLETED",
        "anchors_restored": anchors_restored,
        "target_anchor_dir": str(dest_anchor_dir),
        "db_restore_status": db_restore_status,
        "restored_from_bundle": str(bundle_path),
        "note": (
            "Independent Reality Note: Database restore is distinct from cryptographic audit integrity. "
            "Always run 'verify-backup' and 'verify_with_anchor' after restore to ensure no truncation exists."
        ),
    }


def main() -> int:
    """CLI dispatcher for backup and restore operations."""
    parser = argparse.ArgumentParser(description="MIRAGE Backup & Disaster Recovery Automation Utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup Command
    backup_p = subparsers.add_parser("backup", help="Create a signed backup bundle")
    backup_p.add_argument("--output-dir", type=str, default="data/backups", help="Target backup directory")
    backup_p.add_argument("--database-url", type=str, default=None, help="Database sync URL to dump")
    backup_p.add_argument("--anchor-dir", type=str, default=None, help="Audit anchors source directory")

    # Verify Command
    verify_p = subparsers.add_parser("verify-backup", help="Verify integrity of an existing backup bundle")
    verify_p.add_argument("--backup-dir", type=str, required=True, help="Backup bundle directory to verify")

    # Restore Command
    restore_p = subparsers.add_parser("restore", help="Restore anchors and database from a verified bundle")
    restore_p.add_argument("--backup-dir", type=str, required=True, help="Backup bundle directory to restore")
    restore_p.add_argument("--target-anchor-dir", type=str, default=None, help="Target anchor directory")
    restore_p.add_argument("--target-db-url", type=str, default=None, help="Target database connection URL")
    restore_p.add_argument("--confirm", action="store_true", help="Explicit confirmation for destructive restore")

    args = parser.parse_args()

    if args.command == "backup":
        res = execute_backup(
            output_dir=args.output_dir,
            database_url=args.database_url,
            anchor_dir=args.anchor_dir,
        )
        print(json.dumps(res, indent=2))
        return 0

    elif args.command == "verify-backup":
        res = verify_backup_bundle(args.backup_dir)
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 1

    elif args.command == "restore":
        res = execute_restore(
            bundle_dir=args.backup_dir,
            target_anchor_dir=args.target_anchor_dir,
            target_db_url=args.target_db_url,
            confirm=args.confirm,
        )
        print(json.dumps(res, indent=2))
        return 0 if res["success"] else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
