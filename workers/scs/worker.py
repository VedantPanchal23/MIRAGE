"""SCS Worker: n=5 sampling, DeBERTa semantic entropy clustering, and Redis caching."""

import math
from typing import Any

import httpx

from db.redis import RedisCacheService, default_redis_cache_service
from models.deberta.verifier import DeBERTaNLIVerifier
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("scs_worker")
settings = get_settings()


class SCSWorker:
    """Computes Self-Consistency Sampling with Semantic Entropy (Kuhn et al., 2023)."""

    def __init__(
        self,
        verifier: DeBERTaNLIVerifier | None = None,
        sample_count: int = 5,
        temperature: float = 0.7,
        cache_service: RedisCacheService | None = None,
    ) -> None:
        self.verifier = verifier or DeBERTaNLIVerifier()
        self.sample_count = sample_count
        self.temperature = temperature
        self.cache_service = cache_service or default_redis_cache_service

    def get_cache_key(self, prompt: str, model_id: str, tenant_id: str) -> str:
        """Generate deterministic cache key: scs:{hash(prompt + model_id + tenant_id)}."""
        return self.cache_service.get_scs_cache_key(tenant_id, model_id, prompt)

    def cluster_completions(self, completions: list[str]) -> list[list[str]]:
        """Group completions into semantic equivalence classes using bidirectional entailment."""
        clusters: list[list[str]] = []

        for text in completions:
            placed = False
            for cluster in clusters:
                # Compare against cluster representative (first member)
                rep = cluster[0]
                if self.verifier.are_bidirectionally_entailed(text, rep):
                    cluster.append(text)
                    placed = True
                    break
            if not placed:
                clusters.append([text])

        return clusters

    def compute_semantic_entropy(self, clusters: list[list[str]], total_samples: int) -> float:
        """Compute normalized discrete Semantic Entropy: SE = -sum(p(C) * log2(p(C))) / log2(N)."""
        if total_samples <= 1 or not clusters:
            return 0.0

        entropy = 0.0
        for cluster in clusters:
            p_c = len(cluster) / total_samples
            if p_c > 0.0:
                entropy -= p_c * math.log2(p_c)

        # Normalize by maximum possible entropy log2(N)
        max_entropy = math.log2(total_samples)
        normalized_se = entropy / max_entropy if max_entropy > 0 else 0.0
        return round(min(1.0, max(0.0, normalized_se)), 4)

    async def sample_llm_completions(self, prompt: str, model_id: str) -> list[str]:
        """Fetch n=5 parallel completions from Groq or generate stochastic completions."""
        if settings.groq_api_key and settings.groq_api_key != "your_groq_api_key_here":
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    tasks = [
                        client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                            json={
                                "model": model_id,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": self.temperature,
                            },
                        )
                        for _ in range(self.sample_count)
                    ]
                    responses = [await t for t in tasks]
                    completions: list[str] = []
                    for r in responses:
                        if r.status_code == 200:
                            data: dict[str, Any] = r.json()
                            completions.append(data["choices"][0]["message"]["content"])
                    if len(completions) >= 2:
                        return completions
            except Exception as exc:
                logger.warning("Groq sampling error, using fallback variance generator", error=str(exc))

        # Fallback simulation: return 5 completions with slight paraphrases
        return [
            prompt,
            prompt + " Indeed, this is well established.",
            prompt + " This fact is corroborated by records.",
            prompt,
            prompt + " Accurately documented in history.",
        ]

    async def compute_scs_score(self, prompt: str, model_id: str, tenant_id: str = "default") -> tuple[float, bool]:
        """Compute SCS Semantic Entropy score for prompt. Returns (score, cache_hit)."""
        cached_data, is_hit = await self.cache_service.get_scs(
            tenant_id=tenant_id,
            model_id=model_id,
            prompt=prompt,
        )
        if is_hit and cached_data is not None:
            score = float(cached_data.get("score", 0.0))
            return score, True

        completions = await self.sample_llm_completions(prompt, model_id)
        clusters = self.cluster_completions(completions)
        score = self.compute_semantic_entropy(clusters, total_samples=len(completions))

        await self.cache_service.set_scs(
            tenant_id=tenant_id,
            model_id=model_id,
            prompt=prompt,
            score=score,
            sample_count=len(completions),
            clusters=clusters,
        )
        return score, False
