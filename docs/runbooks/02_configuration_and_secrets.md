# Runbook 02: Configuration Validation and Secret Provisioning

## 1. Overview and Security Principles
MIRAGE follows 12-Factor application configuration principles with strict fail-closed enforcement in production mode (`ENVIRONMENT=production`).
- Default development secrets (e.g. `mirage_dev_secret`, `dev-insecure-secret-key-...`) are strictly rejected.
- Celery broker must enforce AMQPS (TLS 1.2+).
- Insecure development flags (`DEMO_AUTH_ENABLED`, `ALLOW_MOCK_PROVIDERS`, `ALLOW_DEV_NOTARY_KEYS`) must remain `false`.

## 2. Production Secret Generation Procedures

### 2.1 JWT & Cryptographic HMAC Secret (`SECRET_KEY`)
Must be at least 48 characters (384+ bits) of high-entropy cryptographic randomness:
```bash
openssl rand -hex 32
```
Export as `SECRET_KEY`.

### 2.2 Notary Key Registry (`NOTARY_KEYS_JSON`)
External audit checkpoints require authorized notary signing keys formatted as a JSON object:
```bash
# Generate primary notary key
NOTARY_PRIMARY_KEY=$(openssl rand -hex 32)

# Generate JSON payload
echo "{\"notary:system_primary\":\"${NOTARY_PRIMARY_KEY}\"}"
```
Export as `NOTARY_KEYS_JSON`.

### 2.3 Backing Store Database Passwords
Generate dedicated credentials for the migration administrator role and unprivileged runtime application role:
```bash
POSTGRES_ADMIN_PW=$(openssl rand -base64 24)
POSTGRES_APP_PW=$(openssl rand -base64 24)
REDIS_APP_PW=$(openssl rand -base64 24)
RABBITMQ_PW=$(openssl rand -base64 24)
```

## 3. Configuration Validation Execution

Operators must validate production settings prior to rolling deployments:
```bash
python -c "
from shared.config import get_settings
s = get_settings()
defects = s.validate_production_configuration()
if defects:
    print('FATAL CONFIGURATION DEFECTS DETECTED:')
    for d in defects:
        print(f'  - {d}')
    exit(1)
print('Configuration validation passed: Production ready.')
"
```

## 4. HashiCorp Vault / KMS Injection (Kubernetes / Enterprise)
When deployed to Kubernetes or enterprise clusters:
1. Mount secrets using CSI Secret Store Driver (`secrets-store.csi.k8s.io`).
2. Map vault paths directly to container environment variables:
   - `secret/mirage/production/jwt` -> `SECRET_KEY`
   - `secret/mirage/production/notary` -> `NOTARY_KEYS_JSON`
   - `secret/mirage/production/database` -> `DATABASE_URL`
3. Never bake `.env` files into container image layers.
