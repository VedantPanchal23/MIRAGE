"""RAV Worker: Qdrant vector retrieval and document support scoring."""

from typing import Any

from qdrant_client import QdrantClient

from gateway.middleware.circuit_breaker import qdrant_circuit
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas import Claim, EvidenceChunk

logger = get_logger("rav_worker")
settings = get_settings()


class RAVWorker:
    """Retrieves grounding evidence from Qdrant and computes retrieval support scores."""

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self.host = host or settings.qdrant_host
        self.port = port or settings.qdrant_port
        self._client: QdrantClient | None = None
        self._local_docs: list[EvidenceChunk] = []

        try:
            self._client = QdrantClient(
                host=self.host,
                port=self.port,
                api_key=settings.qdrant_api_key,
                timeout=1,
                check_compatibility=False,
            )
        except Exception as exc:
            logger.warning("Could not connect to Qdrant, using in-memory store", error=str(exc))
            self._client = None

    def add_mock_document(
        self,
        chunk_id: str,
        content: str,
        doc_id: str = "doc_default",
        generation: int = 1,
        tenant_id: str | None = None,
    ) -> None:
        """Add in-memory document chunk for testing and offline environments."""
        metadata: dict[str, Any] = {
            "document_id": doc_id,
            "generation": generation,
            "doc_generation": f"{doc_id}:g{generation}",
        }
        if tenant_id:
            metadata["tenant_id"] = tenant_id
        self._local_docs.append(
            EvidenceChunk(
                chunk_id=chunk_id,
                document_id=doc_id,
                content=content,
                similarity_score=1.0,
                source_metadata=metadata,
            )
        )

    async def search_evidence(
        self,
        query: str,
        tenant_id: str | None = None,
        collection_name: str = "default_kb",
        limit: int = 3,
        authoritative_generations: dict[str, int] | None = None,
    ) -> list[EvidenceChunk]:
        """Query vector database for most similar evidence passages.

        Invariant:
        Once PostgreSQL declares generation N as the authoritative indexed generation,
        retrieval must NEVER return vectors belonging to generation < N, even if
        post-commit cleanup has not completed or permanently fails.
        """
        # 1. Check in-memory mock collection first if populated (test/mock fast path)
        if self._local_docs:
            q_lower = query.lower()
            scored: list[EvidenceChunk] = []
            for doc in self._local_docs:
                meta = doc.source_metadata or {}
                doc_tenant = meta.get("tenant_id")
                # If mock document was explicitly scoped to a tenant, respect isolation:
                if tenant_id and doc_tenant and doc_tenant != tenant_id:
                    continue

                words_q = set(q_lower.split())
                words_d = set(doc.content.lower().split())
                sim = len(words_q.intersection(words_d)) / max(len(words_q), 1)
                scored.append(
                    EvidenceChunk(
                        chunk_id=doc.chunk_id,
                        document_id=doc.document_id,
                        content=doc.content,
                        similarity_score=min(1.0, sim),
                        source_metadata=doc.source_metadata,
                    )
                )
            scored.sort(key=lambda x: x.similarity_score, reverse=True)
            return scored[:limit]

        # 2. Query Qdrant if client is connected and circuit breaker is not OPEN
        # Resolve authoritative indexed generations from PostgreSQL if tenant_id provided
        active_gens = authoritative_generations
        if active_gens is None and tenant_id:
            try:
                from db.persistence import default_persistence_service

                active_gens = await default_persistence_service.get_active_kb_generations(tenant_id)
            except Exception as exc:
                logger.warning("Could not query active KB generations from PostgreSQL", error=str(exc))
                active_gens = None

        # If tenant_id was provided and tenant has NO indexed documents in DB, return empty immediately
        if tenant_id is not None and active_gens is not None and len(active_gens) == 0:
            return []

        if self._client is not None and qdrant_circuit.current_state != "open":
            try:
                from qdrant_client.http import models as qmodels

                from workers.rav.ingestion import compute_deterministic_embedding

                # Build authoritative generation filter
                filter_conditions: list[qmodels.Condition] = []
                if tenant_id:
                    filter_conditions.append(
                        qmodels.FieldCondition(
                            key="tenant_id",
                            match=qmodels.MatchValue(value=tenant_id),
                        )
                    )
                if active_gens is not None:
                    allowed_tokens = [f"{did}:g{gen}" for did, gen in active_gens.items()]
                    if not allowed_tokens:
                        return []
                    filter_conditions.append(
                        qmodels.FieldCondition(
                            key="doc_generation",
                            match=qmodels.MatchAny(any=allowed_tokens),
                        )
                    )

                query_filter = qmodels.Filter(must=filter_conditions) if filter_conditions else None

                def _do_query() -> Any:
                    assert self._client is not None
                    return self._client.query_points(
                        collection_name=collection_name,
                        query=compute_deterministic_embedding(query, dim=768),
                        query_filter=query_filter,
                        limit=limit,
                    ).points

                results = qdrant_circuit.call(_do_query)
                evidence: list[EvidenceChunk] = []
                for hit in results:
                    payload: dict[str, Any] = hit.payload or {}
                    hit_tenant = payload.get("tenant_id")
                    hit_doc_id = payload.get("document_id")
                    hit_gen = payload.get("generation")

                    # Defense-in-depth: enforce active generation and tenant isolation
                    if tenant_id and hit_tenant and hit_tenant != tenant_id:
                        continue
                    if active_gens is not None:
                        if hit_doc_id not in active_gens or hit_gen != active_gens[hit_doc_id]:
                            continue

                    evidence.append(
                        EvidenceChunk(
                            chunk_id=str(hit.id),
                            document_id=payload.get("document_id", "unknown"),
                            content=payload.get("text", ""),
                            similarity_score=float(hit.score),
                            source_metadata=payload,
                        )
                    )
                return evidence
            except Exception as exc:
                logger.debug("Qdrant search fallback to empty", error=str(exc))

        return []

    def compute_rav_score(self, _claim: Claim, evidence_chunks: list[EvidenceChunk]) -> float:
        """Compute RAV risk score: 0.0 (strongly supported) to 1.0 (unsupported)."""
        if not evidence_chunks:
            # KB sparsity: No matching documents found
            return 0.85

        top_similarity = max((c.similarity_score for c in evidence_chunks), default=0.0)

        if top_similarity >= 0.70:
            # Strong evidence support
            risk = (1.0 - top_similarity) * 0.5
        elif top_similarity >= 0.40:
            # Moderate support
            risk = 0.30 + (0.70 - top_similarity) * 0.8
        else:
            # Weak or negligible support
            risk = 0.80

        return round(min(1.0, max(0.0, risk)), 4)
