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
            self._client = QdrantClient(host=self.host, port=self.port, timeout=1, check_compatibility=False)
        except Exception as exc:
            logger.warning("Could not connect to Qdrant, using in-memory store", error=str(exc))
            self._client = None

    def add_mock_document(self, chunk_id: str, content: str, doc_id: str = "doc_default") -> None:
        """Add in-memory document chunk for testing and offline environments."""
        self._local_docs.append(
            EvidenceChunk(
                chunk_id=chunk_id,
                document_id=doc_id,
                content=content,
                similarity_score=1.0,
            )
        )

    async def search_evidence(
        self, query: str, collection_name: str = "default_kb", limit: int = 3
    ) -> list[EvidenceChunk]:
        """Query vector database for most similar evidence passages."""
        # 1. Check in-memory mock collection first if populated
        if self._local_docs:
            q_lower = query.lower()
            scored: list[EvidenceChunk] = []
            for doc in self._local_docs:
                words_q = set(q_lower.split())
                words_d = set(doc.content.lower().split())
                sim = len(words_q.intersection(words_d)) / max(len(words_q), 1)
                scored.append(
                    EvidenceChunk(
                        chunk_id=doc.chunk_id,
                        document_id=doc.document_id,
                        content=doc.content,
                        similarity_score=min(1.0, sim),
                    )
                )
            scored.sort(key=lambda x: x.similarity_score, reverse=True)
            return scored[:limit]

        # 2. Query Qdrant if client is connected and circuit breaker is not OPEN
        if self._client is not None and qdrant_circuit.current_state != "open":
            try:

                def _do_query() -> Any:
                    assert self._client is not None
                    return self._client.query_points(
                        collection_name=collection_name,
                        query=[0.1] * 768,  # placeholder representation
                        limit=limit,
                    ).points

                results = qdrant_circuit.call(_do_query)
                evidence: list[EvidenceChunk] = []
                for hit in results:
                    payload: dict[str, Any] = hit.payload or {}
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
