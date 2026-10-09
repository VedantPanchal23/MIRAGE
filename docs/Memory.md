# MIRAGE 3.0 — Memory Governance

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document specifies the governed memory architecture for MIRAGE 3.0.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md).

---

## 1. Introduction

In MIRAGE 3.0, memory is not merely a vector database. It is a strictly governed, provenance-tracked, and access-controlled subsystem. Ungoverned memory inevitably accumulates poisoned data, stale facts, contradictions, and privilege escalation vectors. MIRAGE treats memory as an extension of the Zero Trust architecture.

This document defines the types of memory, their metadata, governance rules, isolation requirements, storage mapping, and integration with the Assurance Gates.

---

## 2. Memory Types and Scopes

Memory in MIRAGE is categorized by its temporal persistence and scope of access.

### 2.1 Temporal Categories
- **Short-term Memory:** Exists only within the boundaries of a single AI Transaction. Used for intermediate reasoning and plan generation. Discarded immediately after the transaction completes.
- **Working Memory:** Persists across a single session (e.g., a chat conversation or multi-step agent workflow). Expires when the session ends or times out.
- **Episodic Memory:** Persistent history of past interactions, transactions, and outcomes. Highly structured and immutable once written.
- **Semantic Memory:** Generalized facts, knowledge, and rules extracted from episodes or provided explicitly (e.g., RAG knowledge bases).
- **Long-term Memory:** Any persistent memory spanning multiple sessions.

### 2.2 Access Scopes
- **Agent-Specific:** Memory accessible only to a specific agent identity.
- **User-Specific:** Memory about a specific user's preferences or facts, accessible only when interacting with that user.
- **Organizational (Tenant-wide):** Shared knowledge base accessible to all authorized agents within a tenant.

---

## 3. Memory Metadata

Every persistent memory item MUST include the following metadata. Memory without this metadata is rejected by the Context Assembler.

- **ID:** Unique identifier (UUIDv7).
- **Tenant ID:** The tenant boundary this memory belongs to.
- **Owner ID:** The agent, user, or system that created the memory.
- **Source:** Where the information came from (e.g., user input, tool output, document ingestion).
- **Provenance:** The verifiable chain of origin (e.g., `Transaction_ID: 12345 -> Tool: WebSearch -> URL: example.com`).
- **Timestamp:** Creation and last modification time.
- **Creation Reason:** Why this memory was stored (Intent).
- **Purpose:** Intended use of this memory.
- **Confidence:** Initial trust score of the information (0.0 to 1.0).
- **Sensitivity:** Classification level (e.g., Public, Internal, Confidential, Restricted, PII).
- **Integrity Hash:** SHA-256 hash of the memory content and metadata to detect tampering.
- **Expiration (TTL):** Time-to-live after which the memory must be purged or archived.
- **Modification History:** Audit trail of updates to this memory item.

---

## 4. Memory Governance

Memory operations are strictly governed by the Policy Engine.

### 4.1 Read Authorization
Retrieving memory requires capability authorization. An agent must have the explicit right to access a specific memory scope or sensitivity level. For example, an agent processing a public inquiry cannot access memory tagged as `Confidential`.

### 4.2 Write Authorization and Mutation Tracking
Writing or updating long-term memory is an Action. It requires capability authorization and is subject to Gate 3 (Action Assurance). Updates to existing memory do not overwrite the original record; they create a new version, preserving the modification history.

### 4.3 Deletion and Expiration Enforcement
Memory deletion is a governed action. When memory is deleted, an audit record of the deletion is maintained, but the content is cryptographically shredded. Expiration (TTL) is enforced aggressively; stale memory is automatically purged from active retrieval systems.

### 4.4 Poisoning Protection & Epistemic Separation
Memory ingestion is subject to Gate 1 (Input Assurance) and Gate 4 (Output Assurance). Any attempt to inject instructions (indirect prompt injection) into memory is detected and blocked.

To prevent memory poisoning through unprovable claims, MIRAGE strictly bifurcates persistent memory into two epistemological tiers:
1. **Attested Memory (High Trust):**
   - **Attestation Authority:** Can ONLY be created by an authenticated human user (via explicit UI confirmation) or ingested through a cryptographically signed enterprise document pipeline.
   - **Prohibition of Self-Attestation:** An LLM or autonomous agent CAN NEVER attest its own generation. Model-generated summaries, extractions, or conclusions are unconditionally tagged as Inferred/Advisory.
   - **Tool Output Ingestion:** Outputs from external tools or MCP servers (e.g., search results, scraped pages) can NEVER automatically become Attested Memory.
   - **Precondition Eligibility:** Only Attested Memory is eligible to serve as authoritative grounding for Gate 3 Action preconditions.
2. **Inferred / Advisory Memory (Low Trust):**
   - User preferences, conversation summaries, or working notes extracted autonomously by the model.
   - Marked with an immutable `ADVISORY` trust flag.
   - **Non-Negotiable Invariant:** Advisory memory can NEVER be used as authoritative evidence to satisfy Gate 3 Action preconditions or authorize consequential state mutations!

### 4.5 Provenance Verification
Before memory is loaded into context, its integrity hash and provenance chain are verified. If the chain is broken or the hash is invalid, the memory is discarded.

### 4.6 Contradiction Handling
When new information contradicts existing semantic memory, MIRAGE does not silently overwrite.
- **Attested vs. Advisory Conflict:** Attested memory strictly supersedes advisory memory. The advisory memory is pruned or tagged as contradicted.
- **Attested vs. Attested Conflict:** When two attested records conflict (e.g., conflicting corporate policies), neither is silently overwritten. A contradiction incident is flagged, both items have their confidence score degraded to $0.50$, and transactions relying on either item trigger an L4 human escalation.

### 4.7 Stale Memory Detection
Memory freshness decays over time. The Risk Engine factors in memory age when computing the overall trust of the assembled context. Highly stale memory used in high-risk decisions triggers policy escalation.

---

## 5. Memory Storage Mapping

Different memory types map to optimized data stores within the Data Plane:

- **PostgreSQL:** Stores Memory Metadata, relationships, access control lists (ACLs), and the cryptographic audit trail of mutations. Guarantees ACID compliance and Tenant Isolation (RLS).
- **Qdrant:** Stores vector embeddings of Semantic Memory for fast similarity search. Strictly segregated by tenant namespaces.
- **MongoDB:** Stores full unstructured text and JSON payloads of Episodic Memory and long-term facts. Managed via per-tenant collections with TTL indexes.
- **Redis:** Stores Short-term and Working Memory. Extremely fast read/write, with strict TTL expiration tied to session lifecycles.

---

## 6. Memory Lifecycle

1. **Creation:** Agent proposes storing a fact. Gate 3 authorizes. Gate 4 verifies consistency. System generates metadata, provenance, and hashes.
2. **Access:** Agent queries memory. Context Assembler retrieves candidates. Gate 2 (Context Assurance) filters based on capabilities, trust, and freshness.
3. **Update:** Agent proposes modification. Requires authorization. Original memory is archived; new version is created.
4. **Expiration:** TTL is reached. Background workers purge the content from Qdrant/MongoDB and mark metadata as expired in PostgreSQL.
5. **Deletion/Archival:** Explicit deletion shreds content; archival moves content to cold storage while retaining audit logs.

---

## 7. Memory Search and Trust Scoring

Memory retrieval is not a blind top-K vector search. 

1. **Retrieval:** Initial similarity search via Qdrant.
2. **Filtering:** Policy Engine filters out items the agent lacks authorization to read.
3. **Trust Scoring:** The Context Assembler calculates a dynamic trust score for each retrieved item based on:
   - Initial Confidence
   - Provenance quality (e.g., User explicit input > Web search result)
   - Freshness (decay function over time)
   - Contradiction status
4. **Assembly:** Only memory items exceeding the minimum trust threshold required for the transaction's Risk Level are included in the prompt context.

---

## 8. Relationship to Context Assurance (Gate 2)

Memory Governance provides the foundation for Gate 2 (Context Assurance). While Gate 2 evaluates all context (including live tool outputs and uploaded documents), governed memory is the only context with historical provenance. 

Gate 2 verifies that the memory retrieved has not been tampered with since creation, evaluates its trust score against the current risk context, and ensures that instructions within the memory (if any) are safely isolated from execution context.
