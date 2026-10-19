# Runbook 07: Signing-Key Rotation and Recovery

## 1. Overview and Scope
MIRAGE employs two primary classes of cryptographic signing keys:
1. **Application Token Signing (`SECRET_KEY`):** Symmetric HMAC secret used for JWT bearer authentication and session token verification.
2. **Audit Notary Signing (`NOTARY_KEYS_JSON`):** Key registry containing authorized notary signing keys for Gate 5 checkpoints and external anchor proofs.

## 2. JWT Secret (`SECRET_KEY`) Rotation Procedure

### Phase 1: Preparation
1. Generate a new high-entropy secret (minimum 48 characters):
```bash
NEW_SECRET_KEY=$(openssl rand -hex 32)
```

### Phase 2: Staged Rollout
Because JWT tokens are stateless, rotating `SECRET_KEY` immediately invalidates previously issued tokens unless a grace period or secondary key is configured.
1. Notify active API clients and operators of impending re-authentication requirement.
2. Update `SECRET_KEY` in secrets manager / `.env`.
3. Perform rolling restart of `mirage-gateway`:
```bash
docker compose restart gateway
```
4. Authenticate as administrative user to verify new token issuance:
```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@mirage.ai","password":"..."}'
```

## 3. Notary Signing Key (`NOTARY_KEYS_JSON`) Rotation Procedure
The `NotaryKeyRegistry` natively supports multiple active keys to allow zero-downtime rotation without invalidating historical checkpoints.

### Step 1: Generate New Notary Key
```bash
NEW_NOTARY_KEY=$(openssl rand -hex 32)
```

### Step 2: Update Notary Key Registry
Add the new key with a new versioned signer identity (e.g. `notary:2026_q4`) while retaining the previous key (`notary:system_primary`):
```json
{
  "notary:system_primary": "existing_secret_key_retained_for_verification",
  "notary:2026_q4": "new_random_32_byte_secret_key"
}
```

### Step 3: Configure Primary Signer
Set the application configuration to sign future checkpoints with `notary:2026_q4`.
Historical anchors signed with `notary:system_primary` will continue to verify successfully because the old key remains in the registry!

### Step 4: Retiring Legacy Keys
Only remove a legacy notary key after all checkpoints signed by that key have exceeded their retention period or have been archived to cold evidence bundles.
