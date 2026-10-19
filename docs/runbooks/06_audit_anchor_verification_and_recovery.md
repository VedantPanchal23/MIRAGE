# Runbook 06: Audit-Anchor Verification and Recovery

## 1. Overview and Security Principles
MIRAGE audit records in `audit_logs` are protected by a continuous SHA-256 hash chain (`prev_hash`). To prevent retroactive database manipulation by privileged DBAs, signed checkpoints are committed to external append-only files (`data/audit_anchors/{tenant_id}.anchors.jsonl`).

### Hash Chaining Invariant:
Each anchor proof record contains:
- `anchor_id`: Unique identifier.
- `checkpoint_hash`: The SHA-256 chain hash committed by the anchor.
- `sequence_number`: Monotonic ledger sequence number.
- `prev_anchor_digest`: SHA-256 digest of the immediately preceding anchor proof.
- `anchor_digest`: SHA-256 digest over the current anchor record including `prev_anchor_digest`.

## 2. Anchor Integrity Verification Procedure

### Verify Anchor File Hash Chain:
Run the internal verification utility:
```bash
python -c "
import asyncio
from services.audit_anchor import get_anchor_backend

async def verify(tenant_id):
    backend = get_anchor_backend()
    valid, defects = await backend.verify_anchor_chain(tenant_id)
    if valid:
        print(f'Tenant {tenant_id} anchor chain: VALID')
    else:
        print(f'Tenant {tenant_id} anchor chain: TAMPERED/BROKEN:')
        for d in defects:
            print(f'  - {d}')

asyncio.run(verify('tenant_production_primary'))
"
```

## 3. Handling Integrity Failure Modes

### Case A: Database Truncation Detected (`TRUNCATION_DETECTED`)
- **Symptom:** Database `head_sequence` is strictly LESS than the sequence number committed by the latest external anchor proof (`head_sequence < anchor.sequence_number`).
- **Implication:** Rows were deleted or truncated from the database table `audit_logs` after the anchor was signed and written!
- **Action:**
  1. DO NOT write new records for this tenant.
  2. Preserve database WAL logs and current state for forensic review (see Runbook 12).
  3. Locate the latest trusted backup bundle to determine what records were removed.
  4. NEVER delete the external anchor file to force the database check to pass.

### Case B: Signature or Anchor Digest Mismatch (`ANCHOR_CORRUPTED`)
- **Symptom:** Anchor line JSON does not match HMAC signature or has an unexpected digest.
- **Action:**
  1. Check if notary signing keys were rotated without updating `NOTARY_KEYS_JSON`.
  2. If unauthorized notary key was used, treat as active compromise (see Runbook 08).
