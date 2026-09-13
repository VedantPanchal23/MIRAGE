"""Development & Testing Database Seeder.

Implements Development Workflow §2 & §6:
- Provisions default tenants across free, pro, and enterprise tiers
- Ingests baseline reference knowledge base documents
- Initializes sample verification sessions and unbroken SHA-256 audit log chains
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from analytics.audit_service import register_audit_entry
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from workers.rav.ingestion import KnowledgeBaseIngestionService

logger = get_logger("db_seeder")

DEFAULT_TENANTS: list[dict[str, Any]] = [
    {
        "id": "tenant_free_001",
        "name": "Academic Research Tier",
        "tier": "free",
        "api_key": "mirage_key_free_academic",
        "scs_enabled": True,
        "pii_detection_enabled": True,
    },
    {
        "id": "tenant_pro_002",
        "name": "Clinical Trials Pro Tier",
        "tier": "pro",
        "api_key": "mirage_key_pro_clinical",
        "scs_enabled": True,
        "pii_detection_enabled": True,
    },
    {
        "id": "tenant_ent_003",
        "name": "Global Enterprise Tier",
        "tier": "enterprise",
        "api_key": "mirage_key_enterprise_corp",
        "scs_enabled": True,
        "pii_detection_enabled": True,
    },
]

SEED_DOCUMENTS: list[dict[str, str]] = [
    {
        "filename": "nasa_mars_perseverance_2024.txt",
        "content": (
            "The Perseverance rover landed on Mars in Jezero Crater in February 2021. "
            "In late 2024, the science team confirmed analysis of multiple sedimentary rock cores "
            "collected from ancient river delta deposits. The instruments detected abundant carbonates "
            "and fine-grained clays that are known on Earth to preserve fossilized organic biosignatures. "
            "The rover has traveled over 28 kilometers across the crater floor and rim."
        ),
    },
    {
        "filename": "world_geography_capitals.txt",
        "content": (
            "Tokyo is the official capital city of Japan and the most populous metropolitan area in the world. "
            "Kyoto served as the imperial capital of Japan for over a thousand years "
            "until the Meiji Restoration in 1868. "
            "Paris is the capital and largest city of France, located along the Seine River. "
            "Canberra is the federal capital of Australia, selected in 1908 as a compromise between "
            "Sydney and Melbourne."
        ),
    },
    {
        "filename": "human_physiology_cardiovascular.txt",
        "content": (
            "The human cardiovascular system is driven by a single four-chambered heart "
            "composed of two atria and two ventricles. "
            "Deoxygenated blood returns from the systemic circulation via the vena cava into the right atrium, "
            "passes to the right ventricle, and is pumped to the lungs for gas exchange. "
            "Oxygen-rich blood returns to the left atrium and ventricle before being pumped "
            "systemically through the aorta."
        ),
    },
]


async def seed_knowledge_base() -> int:
    """Seed reference knowledge base documents across tenants."""
    kb = KnowledgeBaseIngestionService()
    total_chunks = 0
    for tenant in DEFAULT_TENANTS:
        tenant_id = tenant["id"]
        for doc in SEED_DOCUMENTS:
            res = await kb.ingest_document(
                filename=doc["filename"],
                content=doc["content"],
                tenant_id=tenant_id,
            )
            total_chunks += int(res.get("chunks_count", 0))
    return total_chunks


def seed_audit_chains() -> int:
    """Seed baseline audit log records with valid cryptographic hash chains."""
    total_entries = 0
    for tenant in DEFAULT_TENANTS:
        tenant_id = tenant["id"]
        prev_hash = "0" * 64

        sample_sessions = [
            ("sess_init_01", 0.042, "LOW"),
            ("sess_init_02", 0.088, "LOW"),
            ("sess_init_03", 0.145, "LOW"),
        ]

        for s_id, hrs, tier in sample_sessions:
            now_iso = datetime.now(UTC).isoformat()
            block_data = f"{prev_hash}:{s_id}:{hrs:.4f}:{now_iso}"
            hash_chain = compute_sha256(block_data)

            entry = {
                "session_id": s_id,
                "tenant_id": tenant_id,
                "hrs_score": hrs,
                "risk_tier": tier,
                "previous_hash": prev_hash,
                "hash_chain": hash_chain,
                "timestamp": now_iso,
                "prompt": "Initial seed verification session.",
                "response": "Guarded baseline response.",
            }
            register_audit_entry(tenant_id, entry)
            prev_hash = hash_chain
            total_entries += 1

    return total_entries


async def run_seed() -> dict[str, Any]:
    """Master seeder coordinating tenant setup, KB ingestion, and audit initialization."""
    logger.info("Starting MIRAGE database seed...")
    kb_chunks = await seed_knowledge_base()
    audit_count = seed_audit_chains()

    logger.info(
        "Database seeding completed successfully",
        tenants=len(DEFAULT_TENANTS),
        kb_chunks=kb_chunks,
        audit_entries=audit_count,
    )
    return {
        "status": "seeded",
        "tenants_count": len(DEFAULT_TENANTS),
        "kb_chunks_ingested": kb_chunks,
        "audit_records_chained": audit_count,
    }


if __name__ == "__main__":
    asyncio.run(run_seed())
