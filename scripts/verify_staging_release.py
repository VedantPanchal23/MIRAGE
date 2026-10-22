#!/usr/bin/env python3
"""MIRAGE 3.0 — AWS Staging Release Preflight Verification Script.

Validates that the checked-out repository state matches the reviewed deployment
target and that all required infrastructure, container, and configuration
artifacts are present, structurally consistent, and compliant with security invariants.

Usage:
    python scripts/verify_staging_release.py [--expected-ref <SHA_OR_TAG>] [--allow-dirty] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_RELEASE_FILES: list[str] = [
    # Container & Compose topology
    "docker-compose.yml",
    "docker-compose.staging.yml",
    "docker/Dockerfile.gateway",
    "docker/Dockerfile.worker",
    "docker/Dockerfile.dashboard",
    "docker/mongo-init.js",
    "docker/postgres-init.sql",
    # Infrastructure as Code
    "infra/terraform/vpc.tf",
    "infra/terraform/ec2.tf",
    "infra/terraform/s3.tf",
    "infra/terraform/iam.tf",
    "infra/terraform/kms.tf",
    "infra/terraform/secrets.tf",
    "infra/terraform/security_groups.tf",
    "infra/terraform/variables.tf",
    "infra/terraform/versions.tf",
    # Core Application & Configuration
    "shared/config/settings.py",
    "gateway/main.py",
    "workers/celery_app.py",
    "db/migrations/env.py",
    # Documentation & Runbooks
    "docs/deployment/aws-private-staging.md",
    "AGENTS.md",
]


def run_git(args: list[str], repo_root: Path) -> str:
    """Run git command and return trimmed stdout."""
    res = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def check_git_revision(repo_root: Path, expected_ref: str | None) -> tuple[bool, str, dict[str, str]]:
    """Verify current git revision and clean status."""
    info: dict[str, str] = {}
    try:
        current_sha = run_git(["rev-parse", "HEAD"], repo_root)
        current_branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
        porcelain_status = run_git(["status", "--porcelain"], repo_root)
        info["sha"] = current_sha
        info["branch"] = current_branch
        info["dirty"] = "true" if porcelain_status else "false"

        if not expected_ref:
            return (
                False,
                "Deployment requires an explicit reviewed release reference (--expected-ref or "
                "MIRAGE_EXPECTED_RELEASE_REF). Deploying unpinned revisions is prohibited.",
                info,
            )

        # Check if expected_ref matches SHA prefix or tag
        try:
            resolved_expected = run_git(["rev-parse", expected_ref], repo_root)
            info["expected_sha"] = resolved_expected
            if current_sha != resolved_expected:
                return (
                    False,
                    f"Current HEAD ({current_sha[:10]}) does not match expected revision "
                    f"{expected_ref} ({resolved_expected[:10]})",
                    info,
                )
        except subprocess.CalledProcessError:
            # If ref cannot be resolved via git rev-parse, check if expected_ref is prefix of current SHA
            if not current_sha.startswith(expected_ref):
                return (
                    False,
                    f"Current HEAD ({current_sha}) does not match expected ref ({expected_ref})",
                    info,
                )

        return True, f"HEAD is at {current_sha[:10]} ({current_branch}) matches expected ref {expected_ref}", info
    except Exception as exc:
        return False, f"Git verification error: {exc}", info


def check_file_presence(repo_root: Path) -> tuple[bool, list[str]]:
    """Check that all required release files exist."""
    missing: list[str] = []
    for rel_path in REQUIRED_RELEASE_FILES:
        full_path = repo_root / rel_path
        if not full_path.exists() or not full_path.is_file():
            missing.append(rel_path)

    # Check migration versions directory has at least one version
    migrations_dir = repo_root / "db" / "migrations" / "versions"
    if not migrations_dir.is_dir() or not any(migrations_dir.glob("*.py")):
        missing.append("db/migrations/versions/*.py")

    return (len(missing) == 0), missing


def check_security_invariants(repo_root: Path) -> tuple[bool, list[str]]:
    """Verify specific pre-provisioning security configurations."""
    violations: list[str] = []

    # 1. Staging Compose must NOT give DATABASE_SYNC_URL or POSTGRES_PASSWORD to gateway or worker
    compose_staging = repo_root / "docker-compose.staging.yml"
    if compose_staging.exists():
        content = compose_staging.read_text(encoding="utf-8")

        # Check gateway and worker sections specifically
        for svc_name in ["gateway:", "worker:"]:
            if svc_name in content:
                svc_block = content.split(svc_name)[1].split("\n\n")[0]
                if "DATABASE_SYNC_URL" in svc_block:
                    violations.append(
                        f"docker-compose.staging.yml gives DATABASE_SYNC_URL to {svc_name.rstrip(':')} — "
                        "application services must not receive migration credentials"
                    )
                if "POSTGRES_PASSWORD" in svc_block:
                    violations.append(
                        f"docker-compose.staging.yml gives POSTGRES_PASSWORD to {svc_name.rstrip(':')} — "
                        "application services must only receive unprivileged app credentials"
                    )

        if "POSTGRES_APP_USER" in content and "mirage-mongodb" in content:
            mongo_section = content.split("mirage-mongodb:")[-1].split("mirage-")[0]
            if "POSTGRES_APP_USER" in mongo_section:
                violations.append("docker-compose.staging.yml wires POSTGRES_APP_USER into MongoDB environment")

    # 2. Security groups must have zero public ingress
    sg_tf = repo_root / "infra" / "terraform" / "security_groups.tf"
    if sg_tf.exists():
        sg_content = sg_tf.read_text(encoding="utf-8")
        if 'cidr_blocks = ["0.0.0.0/0"]' in sg_content and "ingress" in sg_content:
            violations.append(
                "security_groups.tf contains 0.0.0.0/0 ingress — "
                "unsolicited public inbound traffic is strictly forbidden"
            )

    # 3. EC2 host must enforce IMDSv2 and safe secret deserialization
    ec2_tf = repo_root / "infra" / "terraform" / "ec2.tf"
    if ec2_tf.exists():
        ec2_content = ec2_tf.read_text(encoding="utf-8")
        if not re.search(r'http_tokens\s*=\s*"required"', ec2_content):
            violations.append("ec2.tf does not enforce IMDSv2 (http_tokens must be required)")
        if "jq -r" in ec2_content and ".env" in ec2_content:
            violations.append("ec2.tf uses raw jq pipe to create .env instead of canonical fetch_secrets.py utility")

    # 4. S3 Bucket must enforce TLS requests only and block public access
    s3_tf = repo_root / "infra" / "terraform" / "s3.tf"
    if s3_tf.exists():
        s3_content = s3_tf.read_text(encoding="utf-8")
        if not re.search(r'"aws:SecureTransport"\s*=\s*"false"', s3_content):
            violations.append("s3.tf does not enforce TLS-only transport in bucket policy")
        if not re.search(r"block_public_acls\s*=\s*true", s3_content):
            violations.append("s3.tf does not block public access on audit bucket")
        if not re.search(r"object_lock_enabled\s*=\s*var\.enable_s3_object_lock", s3_content):
            violations.append("s3.tf does not configure S3 Object Lock capability")

    return (len(violations) == 0), violations


def main() -> int:
    parser = argparse.ArgumentParser(description="MIRAGE 3.0 AWS Staging Release Preflight")
    parser.add_argument(
        "--expected-ref",
        default=os.environ.get("MIRAGE_EXPECTED_RELEASE_REF"),
        help="Expected commit SHA or release tag to verify against (or MIRAGE_EXPECTED_RELEASE_REF env var)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow uncommitted local changes (warning emitted instead of failure)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    report: dict[str, Any] = {
        "status": "PASS",
        "repo_root": str(repo_root),
        "checks": {},
    }

    # Check 1: Git revision
    rev_ok, rev_msg, git_info = check_git_revision(repo_root, args.expected_ref)
    report["checks"]["git_revision"] = {
        "passed": rev_ok,
        "message": rev_msg,
        "details": git_info,
    }

    # Check 2: Dirty working tree
    is_dirty = git_info.get("dirty") == "true"
    if is_dirty and not args.allow_dirty:
        report["checks"]["clean_tree"] = {
            "passed": False,
            "message": "Repository contains uncommitted working-tree modifications",
        }
    else:
        report["checks"]["clean_tree"] = {
            "passed": True,
            "message": "Working tree is clean" if not is_dirty else "Working tree dirty (allowed by flag)",
        }

    # Check 3: Required file presence
    files_ok, missing_files = check_file_presence(repo_root)
    report["checks"]["required_files"] = {
        "passed": files_ok,
        "missing": missing_files,
    }

    # Check 4: Pre-provisioning security invariants
    sec_ok, sec_violations = check_security_invariants(repo_root)
    report["checks"]["security_invariants"] = {
        "passed": sec_ok,
        "violations": sec_violations,
    }

    all_passed = rev_ok and (not is_dirty or args.allow_dirty) and files_ok and sec_ok

    report["status"] = "PASS" if all_passed else "FAIL"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 70)
        print("  MIRAGE 3.0 — AWS Staging Release Preflight")
        print("=" * 70)
        print(f"Repository Root: {repo_root}")
        print(f"Git Revision:    {rev_msg}")
        print(f"Working Tree:    {'CLEAN' if not is_dirty else 'DIRTY'}")
        file_status = "ALL PRESENT" if files_ok else f"MISSING {len(missing_files)}"
        print(f"Required Files:  {len(REQUIRED_RELEASE_FILES)} verified ({file_status})")
        if missing_files:
            for mf in missing_files:
                print(f"  - MISSING: {mf}")
        print(f"Security Checks: {'PASSED' if sec_ok else 'VIOLATIONS FOUND'}")
        if sec_violations:
            for sv in sec_violations:
                print(f"  - VIOLATION: {sv}")
        print("-" * 70)
        print(f"OVERALL PREFLIGHT DISPOSITION: {report['status']}")
        print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
