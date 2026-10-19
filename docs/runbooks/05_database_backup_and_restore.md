# Runbook 05: Database Backup and Restore

## 1. Overview and Invariants
This runbook guides operators through the backup, integrity verification, and recovery of the relational control plane and external audit anchor records.

### Critical Safety Invariants
1. **Epistemic Distinction:** A successful database restore is NOT equivalent to verified audit integrity. Restoring database tables does not prove the ledger has not been truncated or modified.
2. **Cryptographic Manifest:** Every backup bundle contains a canonical `manifest.json` signed with a SHA-256 digest covering all contained files.
3. **No Blind Regeneration:** Restoring from backup must never automatically fabricate checkpoints or regenerate missing records to silence integrity defects.

## 2. Backup Execution Procedure

### Step 1: Execute Backup Utility
Run the automated backup script to create a timestamped backup bundle:
```bash
python scripts/backup_restore.py backup --output-dir /var/backups/mirage
```

Output:
```json
{
  "status": "BACKUP_COMPLETED",
  "bundle_path": "/var/backups/mirage/mirage_backup_20261019_120000Z",
  "manifest_sha256": "3a8f...92e1",
  "db_dump_status": "PG_DUMP_SUCCESS",
  "anchors_captured": 4
}
```

### Step 2: Verify the Backup Bundle Immediately
Always verify the newly created bundle:
```bash
python scripts/backup_restore.py verify-backup --backup-dir /var/backups/mirage/mirage_backup_20261019_120000Z
```
Ensure `"valid": true` is returned.

## 3. Disaster Recovery and Restore Procedure

### Step 1: Pre-Restore Verification
The restore command automatically verifies the bundle's cryptographic manifest and rejects any tampered or corrupted bundles:
```bash
python scripts/backup_restore.py verify-backup --backup-dir /var/backups/mirage/<bundle_name>
```

### Step 2: Execute Restore
Execute restore with the mandatory safety confirmation flag:
```bash
python scripts/backup_restore.py restore --backup-dir /var/backups/mirage/<bundle_name> --confirm
```

### Step 3: Post-Restore Audit Verification
After restoring the database and audit anchors, verify that the database ledger aligns with the external anchors:
```bash
python -c "
import asyncio
from db.session import get_sessionmaker
from services.audit_ledger import AuditLedgerService

async def check(tenant_id):
    sm = get_sessionmaker()
    async with sm() as session:
        report = await AuditLedgerService.verify_with_anchor(session, tenant_id)
        print(f'Tenant {tenant_id} status: {report.status.value}, valid: {report.chain_valid}')

asyncio.run(check('default_tenant'))
"
```
If `report.status` reports `TRUNCATION_DETECTED` or `CHAIN_ANCHOR_MISMATCH`, an operator investigation is required (see Runbook 06).
