# Runbook 03: Migration Preflight and Execution

## 1. Overview and Invariants
All relational database schema changes in MIRAGE are managed through Alembic.
- **Strict Linear Graph:** Branching migration heads are prohibited. The migration graph must maintain exactly one current head.
- **Role Separation:** Migrations execute under the privileged database owner role (`mirage`). Application services execute under unprivileged `mirage_app` (`NOBYPASSRLS`).
- **Preflight Requirement:** Application containers must never attempt to run migrations on startup; migrations are run via an isolated one-shot runner (`mirage-migration`).

## 2. Preflight Audit Procedure
Before running migrations on production databases, execute the preflight script:
```bash
python scripts/migration_preflight.py --database-url "${DATABASE_SYNC_URL}"
```
Examine the output:
- `status`: Must be `UP_TO_DATE` or `MIGRATIONS_PENDING`.
- `target_head_revision`: Ensure it matches the expected release revision (e.g. `023_governed_mcp_servers`).
- If status is `DIVERGENT_OR_UNKNOWN_REVISION`, DO NOT proceed. Review local vs remote migration history.

## 3. Migration Execution Procedure

### Method A: Docker Compose Migration Runner
```bash
docker compose run --rm migration
```
This spins up the hardened migration container, executes `alembic upgrade head`, and exits.

### Method B: Manual CLI Execution (Emergency or Staging)
```bash
alembic -c alembic.ini upgrade head
```

## 4. Rollback and Downgrade Boundaries

### Downgrading One Revision
If a migration fails or must be rolled back:
```bash
alembic -c alembic.ini downgrade -1
```

### Safety and Data Retention Invariants:
1. **Destructive DDL Caution:** Downgrading past migrations that created RLS policies or dropped legacy columns can cause immediate authorization failures.
2. **Audit Ledger Immutability:** Tables protected by PostgreSQL append-only rules (`audit_logs`) cannot be altered or truncated without explicit DDL ownership.
3. **Verify App Role:** After any downgrade, verify that `mirage_app` still has appropriate permissions:
```sql
SELECT table_name, privilege_type 
FROM information_schema.role_table_grants 
WHERE grantee = 'mirage_app';
```
