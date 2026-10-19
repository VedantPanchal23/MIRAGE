# Runbook 12: Incident Evidence Preservation

## 1. Overview and Legal/Compliance Context
During a suspected security breach, cross-tenant data access attempt, or catastrophic hallucination event, operators must preserve authoritative, tamper-evident forensic evidence.

### Preservation Standards:
- Must preserve cryptographic chain hashes without mutating existing database rows.
- Must capture external audit anchor proofs from `data/audit_anchors`.
- Must export self-contained compliance evidence bundles signed with a SHA-256 digest.

## 2. Evidence Export Procedure

### Step 1: Export Signed Compliance Evidence Bundle via API
```bash
curl -X GET "http://localhost:8000/v1/audit/export?format=bundle" \
  -H "Authorization: Bearer <auditor_or_admin_token>" \
  -o evidence_bundle_$(date +%Y%m%d_%H%M%S).json
```
The returned bundle contains:
- `bundle_id`: Unique forensic identifier.
- `tenant_id`: Scope of preserved evidence.
- `events`: Array of canonical audit log entries with SHA-256 hashes.
- `chain_verification`: Result of database hash chain verification.
- `latest_anchor`: External anchor proof and signature.
- `bundle_digest`: SHA-256 digest computed over the entire canonical payload.

### Step 2: Capture Snapshot of External Anchor Files
Copy the immutable external anchor proofs from the persistent volume:
```bash
docker compose cp gateway:/app/data/audit_anchors /var/forensics/anchors_snapshot_$(date +%Y%m%d_%H%M%S)
```

### Step 3: Compute Forensic Manifest
Compute SHA-256 checksums across all preserved artifacts:
```bash
sha256sum /var/forensics/anchors_snapshot_*/*.jsonl >> /var/forensics/checksums.sha256
```

## 3. Preserving Execution Traces and Payloads
Capture raw MongoDB spans for the affected transaction:
```bash
docker compose exec mongodb mongosh -u root -p "${MONGO_INITDB_ROOT_PASSWORD}" \
  --eval "db.getSiblingDB('mirage_traces').traces.find({transaction_id: '<tx_id>'}).toArray()" \
  > /var/forensics/tx_<tx_id>_spans.json
```

Store all preserved evidence in write-once object storage or offline archival media with strict chain-of-custody documentation.
