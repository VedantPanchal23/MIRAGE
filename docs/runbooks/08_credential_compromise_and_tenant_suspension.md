# Runbook 08: Credential Compromise and Tenant Suspension

## 1. Overview and Security Invariants
In the event of an API key leak, compromised credentials, or suspicious cross-tenant activity, operators must be able to instantly revoke credentials and suspend tenant execution.

### Security Invariants:
1. **Instant Revocation:** Setting `revoked_at = now()` on an API credential immediately invalidates it for all subsequent requests. The PostgreSQL `mirage_resolve_api_credential` function strictly requires `c.revoked_at IS NULL`.
2. **Fail-Closed Tenant Suspension:** Setting tenant status to `SUSPENDED` causes all authentication resolution functions to return 0 rows. All subsequent requests fail with HTTP 401/403.
3. **Audit Trail Preservation:** Credential revocations and tenant suspensions must be recorded as tamper-evident audit events.

## 2. API Key Immediate Revocation Procedure

### Via Administrative API:
```bash
curl -X DELETE http://localhost:8000/v1/auth/api-keys/<key_id> \
  -H "Authorization: Bearer <admin_token>"
```
Expected response: HTTP 200 with `revoked_at` timestamp.

### Direct Database Emergency Revocation (Emergency Access):
If the gateway is inaccessible:
```sql
UPDATE api_credentials 
SET revoked_at = now() 
WHERE key_prefix = '<first_8_chars_of_leaked_key>';
```
Verify the revocation:
```sql
SELECT id, tenant_id, key_prefix, revoked_at 
FROM api_credentials 
WHERE key_prefix = '<first_8_chars_of_leaked_key>';
```

## 3. Tenant Suspension Procedure

### Via Control Plane API:
```bash
curl -X POST http://localhost:8000/v1/admin/tenants/<tenant_id>/suspend \
  -H "Authorization: Bearer <superadmin_token>" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Suspected credential compromise and anomalous egress"}'
```

### Direct Database Emergency Suspension:
```sql
UPDATE tenants 
SET status = 'SUSPENDED', updated_at = now() 
WHERE id = '<tenant_id>';
```

Verify that all subsequent queries under this tenant context fail closed:
```sql
SELECT * FROM mirage_resolve_api_credential('<sha256_hash_of_key>');
-- Must return 0 rows.
```

## 4. Tenant Re-activation Procedure
Only re-activate a suspended tenant after:
1. All existing API keys and sessions for that tenant have been revoked.
2. Fresh API keys have been issued to authorized tenant administrators.
3. An audit integrity report has verified the tenant's ledger and external anchors.

```sql
UPDATE tenants 
SET status = 'ACTIVE', updated_at = now() 
WHERE id = '<tenant_id>';
```
