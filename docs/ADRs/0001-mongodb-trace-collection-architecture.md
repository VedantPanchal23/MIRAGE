# ADR 0001: MongoDB Trace Collection Architecture Resolution

## Status
**Accepted** (2026-09-14)

## Context
A specification conflict was identified across the governing documents regarding the physical collection architecture for MongoDB trace storage:

1. **`Technical_Architecture.md` §7.2**:
   > "Collection `verification_traces`: Stores full verification pipeline trace per session including raw LLM responses, evidence chunks, agent steps, and correction metadata. Schema-flexible to accommodate evolving pipeline outputs."
2. **`Security_Access.md` §9.1 (Data Isolation Design)**:
   > "MongoDB: Each tenant's verification traces are stored in a separate collection (`traces_{tenant_id}`). Application-level tenant_id scoping is applied before all queries as an additional control."
3. **`Testing_Strategy.md` §5.5 (Integration Testing, Scenario 9)**:
   > "Data Isolation (MongoDB): Verify `traces_{tenant_A}` namespace is completely sealed from Tenant B's API key context."
4. **`PRD.md` §FR-AUD-01**:
   > "System shall store full verification trace per response: prompt, response, HRS, SHAP attribution, per-signal scores, evidence, correction — Verified by complete trace payload serialization into PostgreSQL JSONB and MongoDB."

### Conflict Analysis
- `Technical_Architecture.md` describes a single shared collection named `verification_traces`. Under this model, multi-tenancy relies exclusively on application-level query filtering (`{"tenant_id": ...}`), because MongoDB lacks native database-level Row-Level Security (RLS) analogous to PostgreSQL.
- `Security_Access.md` and `Testing_Strategy.md` explicitly mandate physical separation into dedicated per-tenant collections (`traces_{tenant_id}`) supplemented by application-level query filtering as defense-in-depth.
- Leaving this as a runtime configuration toggle (`mongo_use_per_tenant_collections`) violates production engineering standards by introducing two competing architectures into production without an explicit design decision.

## Decision
We select **`traces_{tenant_id}`** as the sole, authoritative physical collection architecture:

1. **Physical Namespace Partitioning**:
   Every tenant's verification traces are persisted into a dedicated collection formatted as `traces_{valid_tenant_id}`.
2. **Elimination of Configuration Toggle**:
   The setting `mongo_use_per_tenant_collections` is removed. The system unconditionally enforces per-tenant collection routing.
3. **Server-Enforced Routing**:
   The caller has zero ability to specify or override the collection name. The collection name is strictly derived by the server from the cryptographically authenticated `tenant_id`.
4. **Identifier Sanitization**:
   All tenant identifiers must satisfy `_validate_identifier` (`^[a-zA-Z0-9_\-]+$`, max length 64) before any collection or query binding, preventing namespace traversal and command injection.
5. **Dual-Layer Defense-in-Depth**:
   In addition to physical collection partitioning, all trace lookup and deletion queries unconditionally inject an exact document filter:
   `{"tenant_id": {"$eq": valid_tenant_id}}`.

## Consequences
- **Positive**: Strict compliance with `Security_Access.md` §9.1 and `Testing_Strategy.md` §5.9. A query defect in application logic cannot leak documents belonging to other tenants because the collection itself contains only documents for that tenant.
- **Positive**: Tenant offboarding / GDPR right-to-deletion cascades can cleanly drop the tenant collection (`db.drop_collection("traces_{tenant_id}")`).
- **Operational Trade-off**: High tenant counts (e.g. >10,000 active tenants) create many WiredTiger collections and open file descriptors. This is acceptable for the defined enterprise architecture target (<500 enterprise tenants) and is addressed in enterprise sharding topology.
