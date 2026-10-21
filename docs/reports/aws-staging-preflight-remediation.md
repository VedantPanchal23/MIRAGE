# MIRAGE 3.0 — AWS Staging Pre-Plan Hardening and Evidence Gate Report

> **Platform:** MIRAGE 3.0 — AI Execution Assurance Platform<br>
> **Repository:** `VedantPanchal23/MIRAGE`<br>
> **Branch:** `main`<br>
> **Baseline Commit:** `2d7b8aa081e6b81d77a0ba1396b79720077c5c0c`<br>
> **Target Environment:** AWS Private Staging (`us-east-1`)<br>
> **Governing Invariant:** *“Control AI before it acts. Verify AI after it acts.”*<br>
> **Cloud Incurrence Policy:** **Zero AWS cloud resources created; zero cloud charges incurred.**

---

## 1. Executive Summary & Verification Baseline

This report documents the resolution of pre-plan deployment blockers, bootstrap secret handling hardening, network mode validation, and S3 Object Lock lifecycle verification prior to preparing a reviewed Terraform plan.

All validations were executed in reproducible local environments (Docker `hashicorp/terraform:1.9.0`, Python 3.13, Docker Compose 2.x). No AWS infrastructure was provisioned, no real secrets were exposed, and no cloud charges were incurred.

---

## 2. Pre-Plan Hardening & Architectural Invariants

### 2.1 Fail-Closed Bootstrap Secret Handling
- **Previous Vulnerability:** `infra/terraform/ec2.tf` generated a shell script that piped raw Secrets Manager JSON through `jq -r` directly into `/opt/mirage/.env`. This approach risked partial file writes on failure, had no quote or dollar-sign escaping for Docker Compose, did not validate mandatory secrets, and did not reject placeholder values.
- **Hardened Architecture:**
  1. Replaced the raw `jq` pipeline in `infra/terraform/ec2.tf` with the canonical, tested [`scripts/fetch_secrets.py`](file:///scripts/fetch_secrets.py) utility.
  2. Packaged `fetch_secrets.py` inside `infra/terraform/scripts/` to ensure self-contained, reproducible Terraform distribution across both local Docker mounts and remote CI runners.
  3. Enforced atomic writes in `write_env_file_secure`: secrets are written to a temporary PID-scoped file (`.{filename}.tmp.{pid}`), flushed and synced (`os.fsync`), assigned restrictive permissions (`0600`), and atomically renamed (`os.replace`). If an error occurs, the temporary file is unlinked and no partially written `.env` is ever left on disk.
  4. Enforced strict validation: Fails closed on missing mandatory secrets (10 platform keys), while keeping optional LLM provider keys optional when empty/unset. Any placeholder values (`REPLACE_WITH_*`, `your_*`, `changeme`, or default dev passwords) abort startup immediately with exit code `2`.
  5. Implemented comprehensive special character escaping: Single quotes, double quotes, backslashes (`\\`), dollar signs (`$$` interpolation prevention), Unicode characters, whitespace, and newlines (`\n`) are preserved safely for Docker Compose.

### 2.2 Network Modes & Egress Isolation
- **Mode A: Cost-Optimized Private Staging with Direct Egress (Default)**:
  - Configuration: `enable_public_edge = true`, `enable_vpc_endpoints = false`
  - Egress: Outbound HTTPS (443) via Internet Gateway to AWS Systems Manager, Secrets Manager, S3, Docker Hub, package repositories, and LLM APIs.
  - Ingress: Host security group strictly enforces **zero public inbound rules** (`ingress = []`). All unsolicited inbound connections are dropped at the hypervisor level.
  - Access: Exclusively via authenticated AWS SSM Session Manager port forwarding tunnels (Gateway: 8000, Dashboard: 8080, Grafana: 3001).
  - Cost: Public IPv4 address fee of \$0.005/hr (~\$3.60/month in `us-east-1`). Zero NAT Gateway costs (\$0/mo) and zero VPC endpoint fees (\$0/mo).
- **Mode B: Strict Private Subnet Mode with PrivateLink Endpoints**:
  - Configuration: `enable_public_edge = false`, `enable_vpc_endpoints = true`
  - Egress: Disables public IPv4 address assignment. Provisions PrivateLink Interface Endpoints for SSM, SSMMessages, EC2Messages, Secrets Manager, and KMS, plus a free S3 Gateway Endpoint (`infra/terraform/vpc_endpoints.tf`).
  - Cost: \$0.01/hr per interface endpoint AZ (5 endpoints * \$7.20/mo = ~\$36.00/month). Public IPv4 fee is eliminated (\$0.00). Direct egress to external LLM APIs requires an outbound proxy or NAT Gateway.
- **Safety Assertion**: Added a Terraform `check "network_mode_safety"` block verifying `var.enable_public_edge || var.enable_vpc_endpoints`, preventing accidental creation of a stranded instance with no route to SSM.

### 2.3 S3 Object Lock Lifecycle & Teardown Realities
- **Storage WORM vs Application Audit Hash Chaining**:
  - S3 Object Lock provides physical storage-layer Write-Once-Read-Many (WORM) immutability.
  - The MIRAGE audit ledger engine provides application-layer cryptographic proof via SHA-256 hash chaining of audit anchor proofs.
  - External notary anchoring provides third-party cryptographic attestation. S3 Object Lock provides durable cold storage but does not substitute for application-level hash chain verification.
- **GOVERNANCE Mode (Staging Default, 90-Day Retention)**:
  - Objects cannot be overwritten or deleted by non-privileged roles.
  - Teardown requires the operator principal to possess `s3:BypassGovernanceRetention` permission. Updated [`scripts/teardown_aws_staging.sh`](file:///scripts/teardown_aws_staging.sh) to query locked versions and purge them using `--bypass-governance-retention` prior to `terraform destroy`.
- **COMPLIANCE Mode (Production Invariant)**:
  - AWS mathematically prohibits object deletion and bucket destruction by **any** IAM identity (including the AWS root account) until the retention period expires.
  - In Compliance mode, `force_destroy` is unconditionally disabled (`force_destroy = false`). Standard automated teardown **cannot delete** a compliance-locked bucket while retained versions exist.

### 2.4 Release Preflight Hardening
- [`scripts/verify_staging_release.py`](file:///scripts/verify_staging_release.py) strictly requires an explicit reviewed release reference (`--expected-ref` or `MIRAGE_RELEASE_REF`), verifies the checked-out commit matches it, and rejects dirty trees by default.
- Verifies substantive security invariants:
  - Zero `0.0.0.0/0` ingress rules in security groups.
  - Absence of `DATABASE_SYNC_URL` and `POSTGRES_PASSWORD` from gateway and worker compose definitions.
  - Correct wiring of `MONGO_APP_USER` in MongoDB compose configuration.
  - IMDSv2 enforcement (`http_tokens = "required"`) in EC2 instance configuration.
  - Elimination of raw `jq` piping to `.env` in user data.
  - TLS-only transport enforcement (`aws:SecureTransport = "false"` deny) and public access block on the S3 audit bucket.

---

## 3. Comprehensive Itemized Cost Inventory (`us-east-1`)

| Cost Category | AWS Resource | Pricing Basis (`us-east-1`) | 24/7 Monthly Estimate | On-Demand (40 hrs/mo) |
| :--- | :--- | :--- | :--- | :--- |
| **Compute** | EC2 `t3.large` (2 vCPU, 8 GB RAM) | \$0.0832 / hour | \$59.90 | \$3.33 |
| **Block Storage** | GP3 Root EBS (50 GB, 3000 IOPS, 125 MB/s) | \$0.08 / GB-month | \$4.00 | \$4.00 (persists when stopped) |
| **Public IPv4** | In-use Public IPv4 (Outbound Egress Only, Mode A) | \$0.005 / hour | \$3.60 | \$0.20 |
| **Encryption** | KMS Customer Managed Key (`alias/mirage-staging`) | \$1.00 / month + \$0.03 / 10k requests | \$1.05 | \$1.05 |
| **Secrets** | AWS Secrets Manager (1 Secret) | \$0.40 / secret-month + \$0.05 / 10k API calls | \$0.45 | \$0.45 |
| **Audit Storage** | S3 Standard (Audit Proofs & Backups ~5 GB) | \$0.023 / GB-month + PUT/GET requests | \$0.20 | \$0.05 |
| **Data Transfer** | Outbound Internet Egress (SSM, LLM APIs) | First 100 GB/month free from AWS | \$0.00 | \$0.00 |
| **Network Endpoints**| NAT Gateway & VPC Endpoints (Mode A) | Not provisioned in Mode A | \$0.00 | \$0.00 |
| **TOTAL** | **Full 12-Container Stack** | — | **~\$69.20 / month** | **~\$9.08 / month** |

---

## 4. Verification Evidence & Command Log

| Validation Target | Exact Command Executed | Exit Code | Result |
| :--- | :--- | :---: | :--- |
| **Terraform Format** | `docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.9.0 fmt -check -diff` | `0` | **CLEAN** |
| **Terraform Validate** | `docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.9.0 validate` | `0` | **SUCCESS** (`Success! The configuration is valid.`) |
| **Base Compose Config** | `docker compose -f docker-compose.yml config --quiet` | `0` | **VALID** |
| **Staging Compose Config** | `docker compose -f docker-compose.yml -f docker-compose.staging.yml config --quiet` | `0` | **VALID** |
| **Compose Round-Trip** | `docker compose --env-file <complex_secrets.env> -f docker-compose.yml -f docker-compose.staging.yml config --quiet` | `0` | **VALID** (Special characters, quotes, dollar signs parsed correctly) |
| **Secret Serializer Unit Tests** | `pytest tests/unit/test_fetch_secrets.py -v` | `0` | **22 passed**, 0 failed |
| **Staging Security Tests** | `pytest tests/security/test_staging_configuration.py tests/security/test_deployment_hardening.py tests/security/test_cors_configuration.py -v` | `0` | **33 passed**, 0 failed |
| **Full Staging Test Suite** | `pytest tests/unit/test_fetch_secrets.py tests/security/test_staging_configuration.py tests/security/test_deployment_hardening.py tests/security/test_cors_configuration.py -v` | `0` | **55 passed**, 0 failed |
| **Code Linting** | `ruff check shared/ scripts/ tests/unit/ tests/security/ db/ infra/` | `0` | **CLEAN** (All rules compliant) |
| **Release Preflight (No Ref)** | `python scripts/verify_staging_release.py --allow-dirty` | `1` | **FAIL-CLOSED** (Explicit release reference required) |
| **Release Preflight (Dirty Tree)**| `python scripts/verify_staging_release.py --expected-ref HEAD` | `1` | **FAIL-CLOSED** (Rejects uncommitted modifications) |

---

## 5. Concluding Disposition

```
READY FOR COST AND PLAN REVIEW — NO AWS RESOURCES CREATED
```
