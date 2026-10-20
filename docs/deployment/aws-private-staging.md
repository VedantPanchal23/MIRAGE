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
| **Staging Cost** | **\$180–\$280 / month**: Fargate vCPU/RAM pricing + ALB (\$22/mo) + NAT Gateways (\$64/mo for 2 AZs). | **~\$60 / month** running 24/7 on `t3.large` (\$0.0832/hr), or **cents per hour** on-demand when testing. Zero NAT Gateway charges. |
| **Security Boundary** | Cloud IAM + ECS security groups. | Dedicated VPC, IMDSv2, EBS encryption via KMS CMK, zero open inbound ports (AWS SSM Session Manager). |
| **Parity with Local** | Divergent networking, task storage limitations, custom configuration. | **100% environment parity** with local reliability, chaos, and smoke test suites. |
| **Operational Friction** | High complexity for ephemeral staging tests and demos. | Fast, single-command bootstrapping, preflight checks, and teardown. |

**Architectural Decision:** We select **Option B (Compact Hardened EC2 Staging Host with Docker Compose)** for private AWS staging. It eliminates unnecessary cloud overhead, prevents expensive NAT gateway and load balancer fees, preserves exact local container topology parity, and enables private access via AWS Systems Manager Session Manager with zero public inbound ports.

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

### PostgreSQL Database
- `POSTGRES_DB`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER` (migration owner)
- `POSTGRES_PASSWORD` (migration owner password)
- `POSTGRES_APP_USER` (unprivileged runtime role: `mirage_app`)
- `POSTGRES_APP_PASSWORD`
- `DATABASE_URL` (async connection string for `mirage_app`)
- `DATABASE_SYNC_URL` (sync connection string for `mirage` migration owner)

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

### Document, Vector & Monitoring Stores
- `MONGO_INITDB_ROOT_USERNAME`
- `MONGO_INITDB_ROOT_PASSWORD`
- `MONGO_APP_USER` (`mirage_app`)
- `MONGO_APP_PASSWORD`
- `MONGO_DB` (`mirage_traces`)
- `MONGO_URI`
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

## 4. Infrastructure Validation Commands

All infrastructure artifacts can be formatted and validated locally without AWS credentials or cloud spend:

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
```

---

## 5. Secure Secret Provisioning Sequence

Secrets are never embedded in Git, container images, or CI workflow definitions. Provisioning adheres to this sequence:

1. **Create Secrets Container in AWS Secrets Manager**:
   The Terraform template creates `mirage/staging/application_secrets` encrypted with a dedicated Customer Managed KMS Key (`alias/mirage-staging`).
2. **Populate Real Credentials Securely**:
   Operators inject high-entropy secrets via the AWS CLI from a secure administrative terminal:
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id mirage/staging/application_secrets \
     --secret-string file://my-secure-staging-secrets.json
   ```
3. **On-Host Runtime Decryption**:
   The EC2 host uses its scoped IAM instance profile (`mirage-staging-staging-host-role`) to call `secretsmanager:GetSecretValue`.
   The `/opt/mirage/fetch_secrets.sh` utility extracts the JSON keys to a root-only (`chmod 600`) `.env` file upon startup.

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

### Step 3: Connect via AWS Systems Manager Session Manager
No public SSH keys or open port 22 are needed:
```bash
INSTANCE_ID=$(terraform output -raw instance_id)
aws ssm start-session --target "$INSTANCE_ID" --region us-east-1
```

### Step 4: Host Bootstrap & Container Launch
Within the interactive SSM terminal:
```bash
sudo su -
cd /opt/mirage

# 1. Fetch encrypted secrets into root-only .env
/opt/mirage/fetch_secrets.sh

# 2. Clone repository at the approved commit
git clone https://github.com/VedantPanchal23/MIRAGE.git repo
cd repo
git checkout 144556e4986c43f52ec3f4a751a0b73a1b027fc7
cp /opt/mirage/.env .env

# 3. Run migration preflight
python3 scripts/migration_preflight.py --target-head 023_governed_mcp_servers

# 4. Launch multi-container staging stack
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
   Verify port 3001 is bound strictly to `127.0.0.1`. Tunnel via SSM:
   `aws ssm start-session --target $INSTANCE_ID --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["3000"],"localPortNumber":["3001"]}'`

---

## 8. Backup & Restore Expectations

- **PostgreSQL**: Daily binary pg_dump snapshots stored in KMS-encrypted S3 (`aws s3 cp s3://mirage-staging-audit-.../backups/`).
- **Audit Anchor Proofs**: Appended to immutable local directory `/app/data/audit_anchors` and mirrored to private S3 audit bucket.
- **Rollback**: If a deployment defect is detected, rollback is triggered via `docker compose -f docker-compose.yml -f docker-compose.staging.yml down`, reverting Git commit, and restoring Postgres snapshot per `docs/runbooks/05_database_backup_and_restore.md`.

---

## 9. Cost Controls & Controlled Teardown

### Billable Resources Inventory
- **EC2 Instance (`t3.large`)**: ~\$0.0832 / hour (~\$2.00 / day).
- **GP3 EBS Root Storage (50 GB)**: ~\$4.00 / month (\$0.08 / GB-mo).
- **KMS Customer Managed Key**: ~\$1.00 / month + \$0.03 per 10,000 requests.
- **S3 Storage & Data Transfer**: < \$0.50 / month for staging volumes.
- **Zero Billable Items**: NAT Gateways (\$0), Application Load Balancers (\$0), Public IPv4 address charges avoided when private or stopped.

### Teardown Procedure
To completely eliminate all ongoing charges:
```bash
./scripts/teardown_aws_staging.sh
```
This script runs `terraform destroy`, verifies zero active EC2 instances, confirms no unattached EBS volumes, and audits for unassociated Elastic IPs.

---

## 10. Status of Artifacts

| Artifact | Location | Status |
| :--- | :--- | :--- |
| Staging Settings & Validation | `shared/config/settings.py` | **Validated Locally** (Fail-closed on dev secrets) |
| Staging Compose Override | `docker-compose.staging.yml` | **Validated Locally** (Zero public DB ports) |
| Terraform IaC Templates | `infra/terraform/*.tf` | **Validated Locally** (KMS, IAM, VPC, EC2, S3) |
| Cost Control & Budget Alerts | `scripts/setup_aws_budget_alerts.sh` | **Prepared** |
| Teardown & Orphan Audit Script | `scripts/teardown_aws_staging.sh` | **Prepared** |
| CI Infrastructure Validation | `.github/workflows/ci.yml` | **Updated** (Builds gateway, worker, dashboard) |
| Live AWS Staging Resources | AWS Cloud (`us-east-1`) | **NOT CREATED** (Pending User Review) |
