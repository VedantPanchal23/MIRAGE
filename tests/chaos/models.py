"""Data models and deterministic proxy definitions for MIRAGE chaos harness (P3.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DependencyName(StrEnum):
    """The 8 authoritative dependencies in the MIRAGE topology subject to chaos testing."""

    REDIS = "redis"
    QDRANT = "qdrant"
    POSTGRES = "postgres"
    RABBITMQ = "rabbitmq"
    NLI = "nli"
    LLAVA = "llava"
    FLAN_T5 = "flan_t5"
    UPSTREAM_LLM = "upstream_llm"


class ToxicType(StrEnum):
    """Supported Toxiproxy toxic fault types."""

    LATENCY = "latency"
    BANDWIDTH = "bandwidth"
    TIMEOUT = "timeout"
    RESET_PEER = "reset_peer"
    SLOW_CLOSE = "slow_close"
    SLICER = "slicer"


class ToxicStream(StrEnum):
    """Network direction for toxic fault application."""

    DOWNSTREAM = "downstream"
    UPSTREAM = "upstream"


@dataclass
class Toxic:
    """Representation of an active or pending Toxiproxy toxic fault."""

    name: str
    type: ToxicType | str
    stream: ToxicStream | str = ToxicStream.DOWNSTREAM
    toxicity: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert toxic model to Toxiproxy JSON request payload."""
        return {
            "name": self.name,
            "type": str(self.type),
            "stream": str(self.stream),
            "toxicity": self.toxicity,
            "attributes": self.attributes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Toxic:
        """Construct Toxic model from Toxiproxy JSON response."""
        return cls(
            name=data["name"],
            type=data["type"],
            stream=data.get("stream", ToxicStream.DOWNSTREAM),
            toxicity=float(data.get("toxicity", 1.0)),
            attributes=data.get("attributes", {}),
        )


@dataclass
class ProxyDefinition:
    """Representation of a Toxiproxy TCP proxy definition."""

    name: str
    listen: str
    upstream: str
    enabled: bool = True
    toxics: list[Toxic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert proxy definition to Toxiproxy JSON request payload."""
        return {
            "name": self.name,
            "listen": self.listen,
            "upstream": self.upstream,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyDefinition:
        """Construct ProxyDefinition from Toxiproxy JSON response."""
        toxics_data = data.get("toxics", [])
        return cls(
            name=data["name"],
            listen=data["listen"],
            upstream=data["upstream"],
            enabled=data.get("enabled", True),
            toxics=[Toxic.from_dict(t) for t in toxics_data],
        )


# Deterministic proxy port and target mappings for the 8 MIRAGE dependencies
DEFAULT_PROXY_DEFINITIONS: dict[DependencyName, ProxyDefinition] = {
    DependencyName.REDIS: ProxyDefinition(
        name="mirage_redis",
        listen="0.0.0.0:26379",
        upstream="redis:6379",
        enabled=True,
    ),
    DependencyName.QDRANT: ProxyDefinition(
        name="mirage_qdrant",
        listen="0.0.0.0:26333",
        upstream="qdrant:6333",
        enabled=True,
    ),
    DependencyName.POSTGRES: ProxyDefinition(
        name="mirage_postgres",
        listen="0.0.0.0:25432",
        upstream="postgres:5432",
        enabled=True,
    ),
    DependencyName.RABBITMQ: ProxyDefinition(
        name="mirage_rabbitmq",
        listen="0.0.0.0:25672",
        upstream="rabbitmq:5672",
        enabled=True,
    ),
    DependencyName.NLI: ProxyDefinition(
        name="mirage_nli",
        listen="0.0.0.0:28085",
        upstream="torchserve:8085",
        enabled=True,
    ),
    DependencyName.LLAVA: ProxyDefinition(
        name="mirage_llava",
        listen="0.0.0.0:28086",
        upstream="tgi:8086",
        enabled=True,
    ),
    DependencyName.FLAN_T5: ProxyDefinition(
        name="mirage_flan_t5",
        listen="0.0.0.0:28087",
        upstream="flan-t5:8087",
        enabled=True,
    ),
    DependencyName.UPSTREAM_LLM: ProxyDefinition(
        name="mirage_upstream_llm",
        listen="0.0.0.0:28088",
        upstream="api.groq.com:443",
        enabled=True,
    ),
}


@dataclass
class HealthStatus:
    """Represents pre- or post-fault health verification state."""

    is_healthy: bool
    healthy_proxies: list[str] = field(default_factory=list)
    unhealthy_proxies: list[str] = field(default_factory=list)
    active_toxics_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)
