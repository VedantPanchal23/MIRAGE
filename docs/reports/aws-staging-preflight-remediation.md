# MIRAGE 3.0 — AWS Staging Pre-Provisioning Blocker Remediation Report

> **Platform:** MIRAGE 3.0 — AI Execution Assurance Platform  
> **Repository:** `VedantPanchal23/MIRAGE`  
> **Branch:** `main`  
> **Baseline Commit:** `1181e33fb4c90448a45ec29cf5c500959b8f6f29`  
> **Target Environment:** AWS Private Staging (`us-east-1`)  
> **Governing Invariant:** *“Control AI before it acts. Verify AI after it acts.”*  
> **Scope:** Cloud Pre-Provisioning Remediation & Artifact Hardening (Zero AWS cloud resources created; zero charges incurred)

---

## 1. Executive Summary

Prior to initiating live cloud infrastructure provisioning for MIRAGE 3.0 private staging, an architectural and source code security review identified seven concrete deployment blockers. These blockers spanned release revision pinning, database privilege separation, document store identity wiring, S3 audit immutability alignment, network perimeter ingress enforcement, fail-closed startup validation on placeholder secrets, and automated CI Terraform validation.

All seven blockers have been remediated in place, validated across local Docker and Python test harnesses, and aligned with the canonical architecture specifications and operational runbooks.

---

## 2. Remediated Blockers & Verification Evidence

### Blocker 1: Deployment Revision Selection & Release Preflight Verification
- **Vulnerability / Defect:** Staging documentation and operational runbooks hardcoded checkout of a stale commit (`144556e...`), risking silent deployment of unintended or unverified code revisions.
- **Remediation:**
  1. Authoring of `scripts/verify_staging_release.py`: An automated preflight verification utility that validates that the active checkout matches the reviewed release target (`--expected-ref` or `MIRAGE_RELEASE_REF`), verifies all 22 required topology and IaC artifacts, confirms clean working-tree status, and checks security invariants.
  2. Updated `docs/deployment/aws-private-staging.md` to require explicit specification of `MIRAGE_RELEASE_REF` and execution of preflight verification prior to any container launch.
- **Verification Evidence:**
  - Tested against mismatched commit `144556e...`: Preflight aborted fail-closed with exit code `1`.
  - Tested against current revision `HEAD`: Passed with exit code `0`.

---

### Blocker 2: Privileged Database Migration Credentials Stripped from Application Runtime
- **Vulnerability / Defect:** `docker-compose.staging.yml` provided `DATABASE_SYNC_URL` and `POSTGRES_PASSWORD` (belonging to migration DDL owner `mirage`) directly to `mirage-gateway` and `mirage-worker`, violating least privilege and risking schema manipulation by runtime processes.
- **Remediation:**
  1. Updated `shared/config/settings.py` to make `database_sync_url: str | None = Field(default=None)` optional for runtime application services.
  2. Updated `db/migrations/env.py` to safely fall back to normalized `database_url` if `database_sync_url` is omitted.
  3. Stripped `DATABASE_SYNC_URL` and `POSTGRES_PASSWORD` from `mirage-gateway` and `mirage-worker` in `docker-compose.staging.yml`.
  4. Preserved migration credentials strictly for the ephemeral `mirage-migration` container.
- **Verification Evidence:**
  - Regression test `test_database_sync_url_optional_for_runtime` passed (exit code `0`).
  - Staging compose inspection test `test_staging_compose_identity_and_credentials_hygiene` confirmed omission of migration credentials from gateway and worker blocks.

---

### Blocker 3: MongoDB Least-Privilege Identity & Dynamic Initialization
- **Vulnerability / Defect:** `docker-compose.staging.yml` erroneously referenced `POSTGRES_APP_USER` in `mirage-mongodb`, and `docker/mongo-init.js` contained hardcoded credentials unable to adapt to environment-driven secrets.
- **Remediation:**
  1. Corrected `docker-compose.staging.yml` to supply `MONGO_APP_USER` and `MONGO_APP_PASSWORD`.
  2. Added `MONGO_APP_USER` and `MONGO_APP_PASSWORD` environment mappings to `mongodb` in `docker-compose.yml`.
  3. Refactored `docker/mongo-init.js` to dynamically read `process.env.MONGO_APP_USER`, `process.env.MONGO_APP_PASSWORD`, and `process.env.MONGO_DB`, creating the unprivileged application user with scoped `readWrite` role on `mirage_traces`.
- **Verification Evidence:**
  - Validated Docker Compose configuration via `docker compose -f docker-compose.yml -f docker-compose.staging.yml config --quiet` (exit code `0`).
  - Unit test `test_staging_compose_identity_and_credentials_hygiene` verified `POSTGRES_APP_USER` is absent and `MONGO_APP_USER` is correctly bound.

---

### Blocker 4: S3 Audit Immutability & Object Lock Teardown Alignment
- **Vulnerability / Defect:** S3 bucket configuration and deployment runbooks contained conflicting claims regarding Object Lock compliance mode and simple bucket teardown. In AWS, an S3 bucket in `COMPLIANCE` mode cannot be deleted by any IAM principal (including root) until the retention period expires.
- **Remediation:**
  1. Added `enable_s3_object_lock` (default `true`), `s3_object_lock_mode` (default `"GOVERNANCE"` for staging), and `s3_object_lock_retention_days` (default `90`) to `infra/terraform/variables.tf`.
  2. Added `aws_s3_bucket_object_lock_configuration` to `infra/terraform/s3.tf` enforcing WORM retention on audit proofs.
  3. Configured `force_destroy` to be conditionally disabled when `s3_object_lock_mode == "COMPLIANCE"`.
  4. Updated `docs/deployment/aws-private-staging.md` to document that `GOVERNANCE` mode allows controlled teardown with `s3:BypassGovernanceRetention`, while `COMPLIANCE` mode provides mathematical immutability suitable for production.
- **Verification Evidence:**
  - `terraform validate` executed via Docker `hashicorp/terraform:1.9.0` succeeded (exit code `0`).

---

### Blocker 5: Zero Unsolicited Public Inbound Access via Security Groups
- **Vulnerability / Defect:** The staging host security group defined dynamic public ingress rules allowing inbound connections from `0.0.0.0/0` on application ports.
- **Remediation:**
  1. Stripped dynamic public ingress rules from `infra/terraform/security_groups.tf`. The staging host security group now strictly enforces `ingress = []` (zero open inbound ports).
  2. All ingress access to the Gateway (8000), Dashboard (8080), and Grafana (3001) is routed exclusively through authenticated AWS Systems Manager Session Manager (SSM) port forwarding tunnels or shell sessions.
  3. Outbound egress is restricted to HTTPS (port 443) for AWS endpoints, upstream model providers, and verified package repositories.
- **Verification Evidence:**
  - `terraform validate` passed cleanly.
  - `scripts/verify_staging_release.py` enforces zero `0.0.0.0/0` ingress rules in `security_groups.tf`.

---

### Blocker 6: Fail-Closed Placeholder Secret Rejection & Safe Dotenv Serialization
- **Vulnerability / Defect:** Deployments using unfilled placeholder values (`REPLACE_WITH_*`, `your_*`, `changeme`, or development default credentials) could silently start with degraded security postures. Furthermore, JSON secrets from Secrets Manager containing quotes, backslashes, or `$` characters risked corruption during shell expansion.
- **Remediation:**
  1. Implemented `is_insecure_placeholder()` in `shared/config/settings.py` checking for empty values, development defaults (`mirage_dev_secret`, `mirage_redis_secret`, etc.), and placeholder prefixes (`replace_with_`, `your_`, `placeholder`, `changeme`).
  2. Updated `validate_staging_configuration()` and `validate_production_configuration()` to fail closed at startup if mandatory credentials or configured provider API keys contain placeholders.
  3. Authored `scripts/fetch_secrets.py`: A dedicated utility that retrieves AWS Secrets Manager JSON, safely serializes values to Docker Compose `.env` format (escaping `\`, `"`, and `$` to prevent unwanted variable interpolation), validates values against placeholder rules, and sets POSIX file permissions to `0600` (root read/write only).
- **Verification Evidence:**
  - Unit tests `test_placeholder_secrets_rejected_in_staging` and `test_secret_serializer_handles_special_characters` passed.

---

### Blocker 7: CI Automation for Terraform Formatting and Validation
- **Vulnerability / Defect:** The continuous integration workflow (`.github/workflows/ci.yml`) ran `terraform fmt -check`, but lacked `terraform init -backend=false` and `terraform validate` steps to catch syntax or provider configuration errors on pull requests.
- **Remediation:**
  1. Updated `.github/workflows/ci.yml` `infra-validate` job to add `terraform init -backend=false` and `terraform validate` targeting `infra/terraform`.
  2. Pinned Terraform version to `1.9.0` via `hashicorp/setup-terraform@v3`.
  3. Created `.terraform.lock.hcl` and updated `.gitignore` to track provider checksums while ignoring local state and crash logs.
- **Verification Evidence:**
  - Executed identical commands locally inside `hashicorp/terraform:1.9.0` container; all checks exited with code `0`.

---

## 3. Comprehensive Validation Matrix

| Validation Phase | Command Executed | Exit Code | Result |
| :--- | :--- | :--- | :--- |
| **Terraform Formatting** | `docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.9.0 fmt -check -diff` | `0` | **CLEAN** (Formatted per standard) |
| **Terraform Init** | `docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.9.0 init -backend=false` | `0` | **SUCCESS** (AWS 5.100.0 & Random 3.9.1 initialized) |
| **Terraform Validate** | `docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.9.0 validate` | `0` | **SUCCESS** (`Success! The configuration is valid.`) |
| **Base Compose Config** | `docker compose -f docker-compose.yml config --quiet` | `0` | **VALID** (12 services structurally sound) |
| **Staging Compose Config** | `docker compose -f docker-compose.yml -f docker-compose.staging.yml config --quiet` | `0` | **VALID** (Overrides validated without syntax errors) |
| **Security Test Suite** | `pytest tests/security/test_staging_configuration.py tests/security/test_deployment_hardening.py tests/security/test_cors_configuration.py -v` | `0` | **33 PASSED / 0 FAILED** |
| **Code Linting** | `ruff check shared/ scripts/ tests/security/` | `0` | **CLEAN** (All rules compliant) |
| **Release Preflight** | `python scripts/verify_staging_release.py --allow-dirty` | `0` | **PASS** (22 required artifacts & invariants verified) |

---

## 4. Final Disposition

```
AWS PRE-PROVISIONING BLOCKERS RESOLVED — READY FOR COST AND PLAN REVIEW
```
