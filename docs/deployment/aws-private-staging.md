# AWS Private Staging Deployment Guide — MIRAGE 3.0

> **Platform:** MIRAGE 3.0 — AI Execution Assurance Platform  
> **Target Environment:** AWS Private Staging  
> **Status:** Artifacts Prepared & Validated Locally — Ready for Provisioning Review (No AWS resources created during this phase)  
> **Governing Invariant:** *“Control AI before it acts. Verify AI after it acts.”*

---

## 1. Chosen Deployment Architecture & Justification

### 1.1 Architectural Evaluation: Single-EC2 Staging Host vs. Container Orchestration (ECS/EKS)

The MIRAGE 3.0 platform operates 12 integrated services across 3 network tiers:
1. **Core Gateway (`mirage-gateway`)**: FastAPI Execution Plane entry point.
2. **Background Worker (`mirage-worker`)**: Celery daemon for async task processing.
3. **Operator Dashboard (`mirage-dashboard`)**: React 18 / JSX web interface with Nginx reverse proxy.
4. **Relational Control Plane (`mirage-postgres`)**: PostgreSQL 16 with Row-Level Security (RLS).
5. **Trace Document Store (`mirage-mongodb`)**: MongoDB 7 for immutable execution payloads.
6. **Vector Knowledge Store (`mirage-qdrant`)**: Qdrant 1.12 for Gate 2 context embeddings.
7. **Cache & Rate Limiting (`mirage-redis`)**: Redis 7.2 with ACLs and distributed token buckets.
8. **Message Broker (`mirage-rabbitmq`)**: RabbitMQ 3.13 with Quorum Queues.
9. **Distributed Tracing (`mirage-tempo`)**: Grafana Tempo 2.6.
10. **Telemetry Collector (`mirage-otel-collector`)**: OpenTelemetry Collector Contrib 0.108.
11. **Metrics Engine (`mirage-prometheus`)**: Prometheus 2.54.
12. **Monitoring Dashboard (`mirage-grafana`)**: Grafana 11.2 (SSM/SSH port-forwarded only).

#### Deployment Model Comparison Matrix

| Dimension | Option A: ECS Fargate Multi-Task | Option B: Compact Hardened EC2 with Docker Compose (Selected) |
| :--- | :--- | :--- |
| **Footprint** | 12 separate Task Definitions, 12 target groups, complex service discovery. | Exact 12-container Compose topology proven in local staging. |
| **Staging Cost** | **\$180–\$280 / month**: Fargate vCPU/RAM pricing + ALB (\$22/mo) + NAT Gateways (\$64/mo for 2 AZs). | **~\$69 / month** running 24/7 on `t3.large` (\$0.0832/hr) + public IPv4 (\$0.005/hr), or **cents per hour** on-demand when testing. Zero NAT Gateway charges. |
| **Security Boundary** | Cloud IAM + ECS security groups. | Dedicated VPC, IMDSv2, EBS encryption via KMS CMK, zero open inbound ports (AWS SSM Session Manager). |
| **Parity with Local** | Divergent networking, task storage limitations, custom configuration. | **100% environment parity** with local reliability, chaos, and smoke test suites. |
| **Operational Friction** | High complexity for ephemeral staging tests and demos. | Fast, single-command bootstrapping, preflight checks, and teardown. |

**Architectural Decision:** We select **Option B (Compact Hardened EC2 Staging Host with Docker Compose)** for private AWS staging. It eliminates unnecessary cloud overhead, prevents expensive NAT gateway and load balancer fees, preserves exact local container topology parity, and enables private access via AWS Systems Manager Session Manager with zero public inbound ports.

### 1.2 Private-Staging Network Modes & Egress Architecture

The infrastructure supports two distinct network modes configured in `infra/terraform/variables.tf`:

#### Mode A: Cost-Optimized Private Staging with Direct Egress (Default)
- **Configuration**: `enable_public_edge = true`, `enable_vpc_endpoints = false`
- **Network Path**:
  - The staging EC2 host receives a dynamic public IPv4 address (`associate_public_ip_address = true`).
  - The host resides in a public subnet with a default route (`0.0.0.0/0 -> igw`) to an AWS Internet Gateway.
  - **Inbound Security Boundary**: The security group strictly enforces **ZERO public inbound rules** (`ingress = []`). All unsolicited inbound packets from the internet are dropped at the AWS hypervisor stateful firewall. No ports (8000, 8080, 5432, 27017, 3001, 22) are open to the internet.
  - **Outbound Egress**: Direct HTTPS (TCP port 443) to AWS Systems Manager (`ssm.us-east-1.amazonaws.com`, `ssmmessages`, `ec2messages`), AWS Secrets Manager, S3, Docker Hub, Amazon Linux package repositories, and external model provider APIs (Groq, OpenRouter, HuggingFace, OpenAI, Anthropic, Gemini).
  - **Access Model**: Administrative shell and operator dashboard access operate **exclusively** through authenticated AWS Systems Manager Session Manager port forwarding tunnels over outbound TLS.
  - **Cost Profile**: Public IPv4 address fee of \$0.005 / hour (~\$3.60 / month in `us-east-1`). Zero NAT Gateway costs (\$0/mo) and zero VPC Endpoint costs (\$0/mo).

#### Mode B: Strict Private Subnet Mode with PrivateLink Endpoints
- **Configuration**: `enable_public_edge = false`, `enable_vpc_endpoints = true`
- **Network Path**:
  - The EC2 host receives only a private RFC-1918 IP address (`associate_public_ip_address = false`).
  - Outbound internet access via Internet Gateway is disabled.
  - **Internal Connectivity**: Terraform provisions PrivateLink VPC Interface Endpoints for SSM, SSMMessages, EC2Messages, Secrets Manager, and KMS, plus a free S3 Gateway Endpoint.
  - **Egress Boundary**: The host reaches AWS services internally via PrivateLink. However, direct connections to external LLM provider APIs (OpenAI, Anthropic, Groq) and public package repositories are blocked unless a corporate proxy or NAT Gateway is attached.
  - **Cost Profile**: \$0.01 / hour per interface endpoint AZ (5 endpoints * \$7.20/mo = ~\$36.00 / month) + S3 Gateway Endpoint (\$0.00). Eliminates public IPv4 fee (\$0.00).
- **Safety Enforcement**: A Terraform `check "network_mode_safety"` block statically validates that `var.enable_public_edge || var.enable_vpc_endpoints` is true, preventing accidental configuration of a stranded host with no route to SSM.

---

## 2. AWS Account Prerequisites

### Required Prerequisites
- **AWS Account**: Active AWS account with permissions for EC2, VPC, IAM, KMS, Secrets Manager, and S3.
- **AWS CLI v2**: Installed and authenticated locally (`aws sts get-caller-identity`).
- **Terraform v1.5.0+**: Installed locally for plan review and execution.
- **Billing Alerts Enabled**: Spend ceiling budget established before launching EC2 instances.

### Optional Prerequisites
- **Domain & TLS Certificate (ACM)**: Required only if exposing a public HTTPS domain in a future showcase phase. For private staging, internal Nginx self-signed TLS or private reverse-proxying is sufficient.
- **Route 53 Hosted Zone**: Optional for private DNS resolution.

---

## 3. Environment Variable Specification (Names Only)

The staging environment consumes variables exclusively from AWS Secrets Manager (`mirage/staging/application_secrets`) or `.env.example`. **No secret values are stored in version control.**

### Core Platform & Security
- `ENVIRONMENT` (strictly `staging`)
- `DEBUG` (strictly `false`)
- `LOG_LEVEL` (`INFO`)
- `SECRET_KEY` (minimum 32 characters, cryptographically random)
- `DEMO_AUTH_ENABLED` (strictly `false`)
- `ALLOW_MOCK_PROVIDERS` (strictly `false`)
- `CIRCUIT_BREAKER_FAIL_CLOSED_ON_REDIS` (`true`)
- `CORS_ALLOWED_ORIGINS` (comma-separated list of approved dashboard origins)

### PostgreSQL Database (Privilege Separation)
- `POSTGRES_DB`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER` (migration DDL owner: `mirage` — strictly isolated to `migration` container)
- `POSTGRES_PASSWORD` (migration DDL owner password — strictly isolated to `migration` container)
- `POSTGRES_APP_USER` (unprivileged runtime role: `mirage_app` — used by `mirage-gateway` and `mirage-worker`)
- `POSTGRES_APP_PASSWORD`
- `DATABASE_URL` (async connection string for `mirage_app` — provided to runtime services)
- `DATABASE_SYNC_URL` (sync connection string for `mirage` migration owner — provided ONLY to migration runner)

### Redis & Celery Broker
- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_USERNAME` (`mirage_app`)
- `REDIS_PASSWORD`
- `REDIS_URL`
- `CELERY_REDIS_USERNAME` (`mirage_celery`)
- `CELERY_REDIS_PASSWORD`
- `CELERY_RESULT_BACKEND`
- `RABBITMQ_HOST`
- `RABBITMQ_PORT`
- `RABBITMQ_USER` (`mirage`)
- `RABBITMQ_PASSWORD`
- `CELERY_BROKER_URL`

### Document, Vector & Monitoring Stores (Least-Privilege Isolation)
- `MONGO_INITDB_ROOT_USERNAME` (root database administrator)
- `MONGO_INITDB_ROOT_PASSWORD`
- `MONGO_APP_USER` (unprivileged application role: `mirage_app`, provisioned via `docker/mongo-init.js`)
- `MONGO_APP_PASSWORD`
- `MONGO_DB` (`mirage_traces`)
- `MONGO_URI` (application connection string for `mirage_app`)
- `QDRANT_HOST`
- `QDRANT_PORT`
- `QDRANT_API_KEY`
- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

### Upstream LLM Provider API Keys (Optional Subset)
- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`
- `HUGGINGFACE_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`

---

## 4. Infrastructure & Release Validation Commands

All infrastructure artifacts and release revisions can be formatted and validated locally without AWS credentials or cloud spend:

```bash
# 1. Validate Docker Compose base configuration
docker compose -f docker-compose.yml config --quiet

# 2. Validate Docker Compose staging override
docker compose -f docker-compose.yml -f docker-compose.staging.yml config --quiet

# 3. Format and validate Terraform configuration
cd infra/terraform
terraform fmt -check -diff
terraform init -backend=false
terraform validate
cd ../..

# 4. Verify release preflight integrity against reviewed git revision
python3 scripts/verify_staging_release.py --expected-ref HEAD
```

---

## 5. Secure Secret Provisioning Sequence

Secrets are never embedded in Git, container images, or CI workflow definitions. Provisioning adheres to this sequence:

1. **Create Secrets Container in AWS Secrets Manager**:
   The Terraform template creates `mirage/staging/application_secrets` encrypted with a dedicated Customer Managed KMS Key (`alias/mirage-staging`).
2. **Populate Real Credentials Securely**:
   Operators inject high-entropy secrets via the AWS CLI from a secure administrative terminal.
   **Crucial Invariant:** Any placeholder string (`REPLACE_WITH_*`, `placeholder`, `changeme`, or development default passwords) will be **rejected fail-closed** at startup by `Settings` validation in staging and production.
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id mirage/staging/application_secrets \
     --secret-string file://my-secure-staging-secrets.json
   ```
3. **On-Host Runtime Decryption & Safe Dotenv Serialization**:
   The EC2 host uses its scoped IAM instance profile (`mirage-staging-staging-host-role`) to call `secretsmanager:GetSecretValue`.
   The `scripts/fetch_secrets.py` utility retrieves the secret JSON, safely escapes special characters (quotes, backslashes, `$` interpolation prevention), checks for placeholder rejection, and writes a root-only (`chmod 0600`) `.env` file upon startup:
   ```bash
   python3 scripts/fetch_secrets.py \
     --secret-id mirage/staging/application_secrets \
     --region us-east-1 \
     --environment staging \
     --output /opt/mirage/.env
   ```

---

## 6. Preflight & Deployment Sequence

When approved to execute staging deployment:

### Step 1: Pre-Deployment Budget & Billing Safeguards
```bash
./scripts/setup_aws_budget_alerts.sh "devops-alerts@yourcompany.com" 25
```

### Step 2: Terraform Infrastructure Provisioning
```bash
cd infra/terraform
terraform init
terraform plan -out=staging.tfplan
terraform apply staging.tfplan
```

### Step 3: Zero-Inbound Host Access via AWS SSM Session Manager
The staging host security group enforces **ZERO open public inbound ports** (`ingress = []`).
Access operates exclusively via authenticated AWS Systems Manager Session Manager (SSM) port forwarding tunnels or shell sessions:

```bash
INSTANCE_ID=$(terraform output -raw instance_id)

# Start interactive administrative SSM shell session
aws ssm start-session --target "$INSTANCE_ID" --region us-east-1

# Or open private port-forwarding tunnels from your local workstation:
# 1. Gateway API (local port 8000 -> staging gateway 127.0.0.1:8000)
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'

# 2. Operator Dashboard (local port 8080 -> staging dashboard Nginx 127.0.0.1:8080)
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'

# 3. Grafana Monitoring (local port 3001 -> staging grafana 127.0.0.1:3001)
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3001"],"localPortNumber":["3001"]}'
```

### Step 4: Host Bootstrap, Release Verification & Container Launch
Within the interactive SSM terminal:
```bash
sudo su -
cd /opt/mirage

# 1. Fetch encrypted secrets into root-only .env using safe serializer
python3 /opt/mirage/scripts/fetch_secrets.py \
  --secret-id mirage/staging/application_secrets \
  --region us-east-1 \
  --environment staging \
  --output /opt/mirage/.env

# 2. Clone repository at the approved release ref
export MIRAGE_RELEASE_REF="<REVIEWED_COMMIT_SHA_OR_TAG>"
git clone https://github.com/VedantPanchal23/MIRAGE.git repo
cd repo
git checkout "$MIRAGE_RELEASE_REF"

# 3. Execute strict release preflight verification
python3 scripts/verify_staging_release.py --expected-ref "$MIRAGE_RELEASE_REF"

# 4. Copy validated .env into repo working directory
cp /opt/mirage/.env .env

# 5. Run migration preflight using DDL migration credentials
python3 scripts/migration_preflight.py --target-head 023_governed_mcp_servers

# 6. Launch multi-container staging stack
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
```

---

## 7. Health Checks & Acceptance Criteria

Once containers are active, execute the acceptance checklist:

1. **Gateway Health Probe**:
   `curl -s http://127.0.0.1:8000/v1/health | jq .`
   - Status must be `healthy`.
   - Environment must report `staging`.
2. **Gateway Readiness Probe (6 Backends)**:
   `curl -s http://127.0.0.1:8000/v1/ready | jq .`
   - Must return HTTP 200 with all backends reporting `ok` (Postgres, MongoDB, Redis, RabbitMQ, Qdrant, Audit Anchors).
3. **Dashboard Web Proxy**:
   `curl -I http://127.0.0.1:8080/`
   - Must return HTTP 200 with standard security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`).
4. **Grafana Private Access**:
   Verify port 3001 is bound strictly to `127.0.0.1`. Tunnel via SSM port-forwarding.

---

## 8. Backup, S3 Object Lock Lifecycle & Audit Integrity

### 8.1 S3 Object Lock Lifecycle and Teardown Realities
- **Storage-Level WORM Protection**: When `enable_s3_object_lock = true`, the S3 audit bucket enforces Write-Once-Read-Many (WORM) storage. Uploaded audit objects and database backups cannot be overwritten, updated, or prematurely deleted.
- **GOVERNANCE Mode (Staging Default, 90-Day Retention)**:
  - In `GOVERNANCE` mode, objects are protected against accidental mutation or deletion by non-privileged roles.
  - **Teardown Reality**: `terraform destroy` will fail to delete a bucket with active objects unless the objects are first purged using the `x-amz-bypass-governance-retention: true` header. The operator principal must possess explicit `s3:BypassGovernanceRetention` IAM permission. The [`scripts/teardown_aws_staging.sh`](file:///scripts/teardown_aws_staging.sh) script automatically performs this purge when authorized.
- **COMPLIANCE Mode (Production Invariant)**:
  - In `COMPLIANCE` mode, AWS mathematically prohibits object deletion and bucket destruction by **any** IAM identity (including the AWS root account) until the retention period expires.
  - **Teardown Reality**: `force_destroy` is unconditionally disabled (`force_destroy = false`). Standard automated teardown **cannot delete** a compliance-locked bucket while retained versions exist. This constraint is an intentional regulatory compliance safeguard.
- **Distinction Between Storage WORM and Application Audit Verification**:
  - **S3 Object Lock** provides cloud storage-layer immutability (WORM) against disk-level tampering or deletion.
  - **MIRAGE Audit Ledger Engine** provides application-level cryptographic proof via SHA-256 hash chaining of audit anchor proofs.
  - **External Notary Anchoring** provides third-party cryptographic attestation via external notary signatures. S3 Object Lock alone does not prove audit chain continuity; independent mathematical verification is performed by MIRAGE audit validation suites.

---

## 9. Comprehensive Cost Inventory & Controlled Teardown

### 9.1 Itemized Staging Cost Estimate (Region: `us-east-1`)

The following inventory details monthly and on-demand expenses under the selected **Mode A (Cost-Optimized Private Staging)**:

| Cost Category | AWS Resource | Pricing Basis (`us-east-1`) | 24/7 Monthly Estimate | On-Demand (40 hrs/mo) |
| :--- | :--- | :--- | :--- | :--- |
| **Compute** | EC2 `t3.large` (2 vCPU, 8 GB RAM) | \$0.0832 / hour | \$59.90 | \$3.33 |
| **Block Storage** | GP3 Root EBS (50 GB, 3000 IOPS, 125 MB/s) | \$0.08 / GB-month | \$4.00 | \$4.00 (persists when stopped) |
| **Public IPv4** | In-use Public IPv4 (Outbound Egress Only) | \$0.005 / hour | \$3.60 | \$0.20 |
| **Encryption** | KMS Customer Managed Key (`alias/mirage-staging`) | \$1.00 / month + \$0.03 / 10k requests | \$1.05 | \$1.05 |
| **Secrets** | AWS Secrets Manager (1 Secret) | \$0.40 / secret-month + \$0.05 / 10k API calls | \$0.45 | \$0.45 |
| **Audit Storage** | S3 Standard (Audit Proofs & Backups ~5 GB) | \$0.023 / GB-month + PUT/GET requests | \$0.20 | \$0.05 |
| **Data Transfer** | Outbound Internet Egress (SSM, LLM APIs) | First 100 GB/month free from AWS | \$0.00 | \$0.00 |
| **Network Endpoints**| NAT Gateway & VPC Endpoints (Mode A) | Not provisioned in Mode A | \$0.00 | \$0.00 |
| **TOTAL** | **Full 12-Container Stack** | — | **~\$69.20 / month** | **~\$9.08 / month** |

*Note: In Mode B (Strict Private Subnet with VPC Endpoints), add \$36.00/month for 5 PrivateLink interface endpoints and subtract \$3.60/month for public IPv4 (Net total: ~\$101.60/month).*

### 9.2 Safe Zero-Cost Plan Review Protocol

Operators can generate and inspect the complete Terraform execution plan without provisioning AWS resources or incurring cloud spending:

```bash
cd infra/terraform

# 1. Initialize without cloud backend
terraform init -backend=false

# 2. Generate plan file safely (requires read-only AWS credentials)
terraform plan -out=staging.tfplan

# 3. Inspect plan contents without applying
terraform show staging.tfplan

# 4. Alternatively inspect machine-readable plan JSON
terraform show -json staging.tfplan | jq '.resource_changes[] | {type: .type, name: .name, actions: .change.actions}'
```

**Guardrail:** Operators must never run `terraform apply` until the plan has been reviewed and authorized.

### 9.3 Teardown Procedure
To completely eliminate all ongoing charges:
```bash
./scripts/teardown_aws_staging.sh
```
This script empties Object Lock governance-locked objects (if authorized), executes `terraform destroy`, verifies zero active EC2 instances, confirms no unattached EBS volumes, and audits for unassociated Elastic IPs.

---

## 10. Status of Artifacts

| Artifact | Location | Status |
| :--- | :--- | :--- |
| Staging Settings & Validation | `shared/config/settings.py` | **Validated Locally** (Fail-closed on dev secrets & placeholders) |
| Staging Compose Override | `docker-compose.staging.yml` | **Validated Locally** (Zero public DB ports, unprivileged runtime) |
| Database Migration Privilege Separation | `docker/postgres-init.sql` & Compose | **Validated Locally** (`mirage_app` unprivileged, `mirage` migration owner) |
| MongoDB Identity Dynamic Initialization | `docker/mongo-init.js` & Compose | **Validated Locally** (`MONGO_APP_USER` / `mirage_app` least privilege) |
| Terraform IaC Templates | `infra/terraform/*.tf` | **Validated Locally** (Zero inbound SG, S3 Governance Lock, KMS, IAM) |
| PrivateLink VPC Endpoints Configuration | `infra/terraform/vpc_endpoints.tf` | **Validated Locally** (SSM, Secrets Manager, KMS, S3 Gateway) |
| Release Preflight Verifier | `scripts/verify_staging_release.py` | **Tested & Passed** (Enforces ref, clean tree, security checks) |
| Safe Secret Serializer | `scripts/fetch_secrets.py` | **Tested & Passed** (Atomic write, 0600 permissions, Compose round-trip) |
| Cost Control & Budget Alerts | `scripts/setup_aws_budget_alerts.sh` | **Prepared** |
| Teardown & Orphan Audit Script | `scripts/teardown_aws_staging.sh` | **Prepared** (Object Lock governance bypass supported) |
| CI Infrastructure Validation | `.github/workflows/ci.yml` | **Updated** (Runs `terraform fmt`, `init`, and `validate`) |
| Secret Serializer & Staging Unit Tests | `tests/unit/test_fetch_secrets.py` | **Passed 22/22** |
| Staging Security Test Suite | `tests/security/test_staging_configuration.py` | **Passed 16/16** (55/55 across all staging suites) |
| Live AWS Staging Resources | AWS Cloud (`us-east-1`) | **NOT CREATED** (Pending User Review) |
