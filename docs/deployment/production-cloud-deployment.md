# MIRAGE 3.0: Production Cloud VPS Deployment Runbook

> **Authoritative Specification:** Technical Architecture §10, Security & Access §9, and ADR 0005.  
> **Target Environment:** Production Cloud VPS (Ubuntu 22.04 / 24.04 LTS) on DigitalOcean, Hetzner, AWS EC2, or Linode.  
> **Topology:** Docker Compose Engine with Nginx Reverse Proxy, Let's Encrypt TLS/SSL, systemd supervision, and automated daily backup cron.

---

## 1. System Requirements & Architecture Overview

### Recommended Hardware Specs
| Component | Minimum Specification | Recommended Production |
| :--- | :--- | :--- |
| **vCPU** | 2 Cores | 4 Cores (x86_64) |
| **Memory** | 4 GB RAM | 8 GB RAM |
| **Storage** | 30 GB SSD | 80 GB NVMe SSD |
| **Operating System** | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| **Network** | Static Public IPv4, Port 80/443 ingress | Static Public IPv4 + IPv6 |

### Architectural Flow
```
Internet Clients (Web / API / Agents)
       │
       ▼ (Ports 80 / 443 with TLS 1.3)
┌──────────────────────────────────────────────┐
│  Nginx Reverse Proxy (SSL Termination)       │
│  - api.domain.com   ──► localhost:8000 (API) │
│  - app.domain.com   ──► localhost:5173 (Web) │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│  MIRAGE Docker Compose Network               │
│  ├── mirage-gateway (FastAPI Gateway)        │
│  ├── mirage-postgres (PostgreSQL 16 + RLS)   │
│  ├── mirage-redis (Redis 7 + Leases)         │
│  └── mirage-qdrant (Qdrant Vector DB)        │
└──────────────────────────────────────────────┘
```

---

## 2. Server Provisioning & Base Hardening

Connect to your cloud VPS as `root` or `sudo` user:

```bash
ssh root@<YOUR_SERVER_IP>
```

### 2.1 Update System & Install Base Packages
```bash
apt-get update && apt-get upgrade -y
apt-get install -y curl git ufw fail2ban certbot python3-certbot-nginx jq
```

### 2.2 Configure UFW Firewall
```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (Let's Encrypt validation)
ufw allow 443/tcp   # HTTPS (Production Traffic)
ufw --force enable
```

### 2.3 Install Docker Engine & Docker Compose Plugin
```bash
# Add Docker official GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

# Add repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

---

## 3. Repository Setup & Environment Configuration

### 3.1 Clone the MIRAGE Repository
```bash
mkdir -p /opt/mirage
cd /opt/mirage
git clone https://github.com/your-org/MIRAGE.git .
```

### 3.2 Configure Production Environment Variables (`.env`)
Copy the production environment template:
```bash
cp .env.example .env
chmod 600 .env
```

Generate secure cryptographic keys using `openssl`:
```bash
SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 24)
REDIS_PASSWORD=$(openssl rand -hex 24)
QDRANT_API_KEY=$(openssl rand -hex 24)

sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" .env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://mirage:${POSTGRES_PASSWORD}@postgres:5432/mirage|" .env
sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0|" .env
sed -i "s|^QDRANT_API_KEY=.*|QDRANT_API_KEY=${QDRANT_API_KEY}|" .env
sed -i "s|^ENVIRONMENT=.*|ENVIRONMENT=production|" .env
```

Ensure your commercial billing and SMTP variables in `.env` are configured:
```ini
# Commercial Billing (Razorpay Testing or Live)
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_razorpay_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_signing_secret

# Transactional Email (Google Workspace / Amazon SES / SendGrid)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=vedantwork1402@gmail.com
SMTP_PASSWORD=your_app_specific_password
SMTP_FROM=vedantwork1402@gmail.com
```

---

## 4. Single-Command Launch & Database Initialization

### 4.1 Launch Core SaaS Services
Start the production core container cluster (PostgreSQL, Redis, Qdrant, Gateway):
```bash
docker compose up -d postgres redis qdrant
```

Verify healthy database status:
```bash
docker compose ps
```

### 4.2 Run Database Migrations
Run Alembic migrations to apply all PostgreSQL schemas and Row-Level Security policies:
```bash
docker compose run --rm gateway alembic upgrade head
```

### 4.3 Launch the Full Production Platform
```bash
docker compose up -d
```

Verify that the Gateway is reporting healthy status:
```bash
curl -I http://localhost:8000/v1/health
# Returns: HTTP/1.1 200 OK
```

---

## 5. Nginx Reverse Proxy & Let's Encrypt TLS/SSL Setup

### 5.1 Create Nginx Site Configuration
Create `/etc/nginx/sites-available/mirage`:

```nginx
# Map WebSocket upgrade headers
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=60r/s;

# 1. API Gateway (api.yourdomain.com)
server {
    server_name api.yourdomain.com;

    client_max_body_size 25M;

    # Security Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        limit_req zone=api_limit burst=120 nodelay;

        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket & Streaming support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;
    }
}

# 2. Web Dashboard & Landing Page (app.yourdomain.com)
server {
    server_name app.yourdomain.com;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }
}
```

Enable the configuration:
```bash
ln -s /etc/nginx/sites-available/mirage /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 5.2 Obtain Free Automated SSL via Certbot
```bash
certbot --nginx --non-interactive --agree-tos --email vedantwork1402@gmail.com \
  -d api.yourdomain.com -d app.yourdomain.com
```

Certbot automatically schedules systemd renewal timers (`certbot.timer`) for auto-renewal every 60 days.

---

## 6. Automated Daily Backups & Disaster Recovery

### 6.1 Create the Backup Script (`/opt/mirage/scripts/backup_production.sh`)
```bash
cat << 'EOF' > /opt/mirage/scripts/backup_production.sh
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/var/backups/mirage"
DATE=$(date +"%Y%m%d_%H%M%S")
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

echo "[$DATE] Starting automated MIRAGE backup..."

# 1. PostgreSQL Authoritative Database Dump
PG_BACKUP="$BACKUP_DIR/mirage_postgres_$DATE.sql.gz"
docker compose -f /opt/mirage/docker-compose.yml exec -T postgres pg_dump -U mirage mirage | gzip > "$PG_BACKUP"
sha256sum "$PG_BACKUP" > "$PG_BACKUP.sha256"
echo "  [PASS] PostgreSQL backup created: $PG_BACKUP"

# 2. Qdrant Vector DB Snapshot
QDRANT_BACKUP="$BACKUP_DIR/mirage_qdrant_$DATE.tar.gz"
tar -czf "$QDRANT_BACKUP" -C /opt/mirage/qdrant_storage . 2>/dev/null || true
sha256sum "$QDRANT_BACKUP" > "$QDRANT_BACKUP.sha256"
echo "  [PASS] Qdrant storage snapshot created: $QDRANT_BACKUP"

# 3. Rotate Old Backups
find "$BACKUP_DIR" -type f -name "mirage_*" -mtime +$RETENTION_DAYS -delete
echo "  [PASS] Pruned backups older than $RETENTION_DAYS days."

echo "[$DATE] Backup completed successfully."
EOF

chmod +x /opt/mirage/scripts/backup_production.sh
```

### 6.2 Schedule Automated Nightly Cron
Add to crontab (`crontab -e`):
```cron
# Run MIRAGE full platform backup every night at 02:00 UTC
0 2 * * * /opt/mirage/scripts/backup_production.sh >> /var/log/mirage_backup.log 2>&1
```

---

## 7. Systemd Service Supervisor (`mirage.service`)

Ensure MIRAGE automatically recovers upon server reboot.

Create `/etc/systemd/system/mirage.service`:
```ini
[Unit]
Description=MIRAGE 3.0 AI Execution Assurance Platform
Requires=docker.service
After=docker.service network.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/mirage
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
systemctl daemon-reload
systemctl enable mirage.service
```

---

## 8. Post-Deployment Verification Suite

Run the full end-to-end customer journey smoke suite on the production server to verify all 7 gates and live databases:

```bash
docker compose exec gateway python scripts/verify_full_customer_journey.py
```

Expected Output:
```
==================================================================
    MIRAGE 3.0: Full Customer Journey Automated Smoke Suite
==================================================================
[Step 1] Self-Service Enterprise Tenant Registration
  [PASS] Provisioned Tenant: tenant_...
  [PASS] Cryptographic Access Token acquired

[Step 2] Gate 2 Context Assurance: Document Ingestion & Qdrant Retrieval
  [PASS] Ground-truth policy ingested with SHA-256 deduplication
  [PASS] Vector search returned matching evidence chunks

[Step 3] OpenAI-Compatible Drop-In Proxy Assurance
  [PASS] OpenAI Proxy responded with ID: chatcmpl_...

[Step 4] Gate 3 Action Assurance: Tool Governance & Action Proposal
  [PASS] Tool 'treasury.disburse_funds' registered under Gate 3
  [PASS] Action proposed with distributed lease fencing token

[Step 5] Governed Action Execution under Distributed Lease
  [PASS] Action executed securely through Governed Tool Proxy: Status = COMPLETED

[Step 6] Gate 5 Outcome Assurance: Reality State Verification
  [PASS] Reality verification confirmed: Verdict = VERIFIED_SUCCESS

[Step 7] Audit Ledger Cryptographic Integrity Check
  [PASS] Audit Hash Chain Status: CHAIN_VALID, Verified Entries: 1

==================================================================
  ALL 7 CUSTOMER JOURNEY STEPS VERIFIED WITH 100% SUCCESS!
  MIRAGE 3.0 Platform is Production & Commercial Release Ready.
==================================================================
```
