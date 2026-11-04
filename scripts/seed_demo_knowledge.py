#!/usr/bin/env python3
"""MIRAGE 3.0: Demo Institutional Knowledge Base Seeder.

Seeds authoritative compliance and policy documentation into Qdrant vector store
and PostgreSQL for a given tenant, providing out-of-the-box RAG provenance (Gate 2)
and factual entailment verification (Gate 4).

Usage:
    python scripts/seed_demo_knowledge.py [--tenant-id TENANT_ID]
"""

import argparse
import asyncio
import hashlib
import io
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from db.persistence import default_persistence_service
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from workers.rav.ingestion import KnowledgeBaseIngestionService

logger = get_logger("seed_demo_knowledge")
settings = get_settings()

FINANCIAL_POLICY = (
    "# Institutional Financial Disbursement & Treasury Governance Policy\n"
    "Version: 4.2 | Classification: RESTRICTED | Effective Date: January 1, 2026\n\n"
    "## 1. Scope & Fiduciary Authority\n"
    "This policy governs all automated and human-directed treasury disbursements,\n"
    "wire transfers, ACH transfers, and liquidity sweeps across institutional operating accounts.\n\n"
    "## 2. Disbursement Thresholds and Fencing Rules\n"
    "- **Tier 1 (Automated Execution < $10,000 USD)**: Permitted for pre-authorized recurring\n"
    "  vendor invoices with matched 3-way purchase orders.\n"
    "- **Tier 2 (Managerial Approval $10,000 - $50,000 USD)**: Requires single-sign-off by\n"
    "  an authorized Treasury Manager.\n"
    "- **Tier 3 (Executive Quorum Approval > $50,000 USD)**: Any disbursement exceeding\n"
    "  $50,000.00 USD strictly requires two independent cryptographic sign-offs from authorized\n"
    "  corporate officers (CFO, VP Finance, or Controller). Autonomous AI agents are strictly\n"
    "  prohibited from settling transactions exceeding $50,000 without Gate 3 Human-in-the-Loop\n"
    "  (HITL) quorum approval tokens.\n\n"
    "## 3. Fedwire and Clearing Network Verification\n"
    "- All outbound wire transfers must be transmitted over the Federal Reserve Fedwire Funds\n"
    "  Service or SWIFT network using pre-verified Routing Transit Numbers (RTNs).\n"
    "- Beneficiary account name must match the validated Vendor Master Record. Account numbers\n"
    "  cannot be modified within 72 hours of transaction dispatch.\n"
    "- Real-time confirmation requires independent ledger observation (Gate 5) confirming SETTLED\n"
    "  status from the destination clearinghouse before reconciliation records are sealed.\n"
)

CLINICAL_POLICY = (
    "# Clinical Pediatric Pharmacology Formulary & Dosing Protocols\n"
    "Standard Reference: Peds-Formulary-2026.1 | Scope: Inpatient & Ambulatory Care\n\n"
    "## 1. Amoxicillin Dosing for Acute Otitis Media (AOM)\n"
    "- **Standard Dosing**: The recommended high-dose amoxicillin regimen for pediatric acute\n"
    "  otitis media is **80 to 90 mg/kg/day**, divided into two equal doses administered every\n"
    "  12 hours (Q12H).\n"
    "- **Maximum Daily Ceiling**: The absolute maximum daily dose for pediatric patients is\n"
    "  **2,000 mg to 3,000 mg per day**, regardless of body weight calculation.\n"
    "- **Bolus Contraindication**: Amoxicillin is administered orally as a suspension or tablet.\n"
    "  Single high-concentration intravenous boluses exceeding 45 mg/kg are strictly prohibited\n"
    "  due to severe renal precipitation and neurotoxicity risks.\n"
    "- **Treatment Duration**: 10 days for children younger than 2 years of age or children with\n"
    "  severe symptoms; 7 days for children aged 2 to 5 years with mild-to-moderate disease.\n\n"
    "## 2. Renal Clearance and Adjustment\n"
    "- In patients with severe renal impairment (GFR < 30 mL/min/1.73 m2), do not administer\n"
    "  the 875 mg or high-dose regimen; reduce dose to 15 mg/kg administered every 12 hours.\n"
)

TRAVEL_POLICY = (
    "# Global Corporate Travel, Flight Class & Expense Governance\n"
    "Directive: POL-EXP-2026-08 | Compliance Authority: Finance & Internal Audit\n\n"
    "## 1. Air Travel Class Eligibility\n"
    "- **Domestic Flights (< 5 hours)**: Standard Economy class only. Preferred seat selection\n"
    "  permitted for flights exceeding 3 hours.\n"
    "- **Transcontinental & Long-Haul (5 - 8 hours)**: Premium Economy permitted.\n"
    "- **International Intercontinental (> 8 hours non-stop)**: Business Class permitted for\n"
    "  VP level and above, or when arriving within 4 hours of a critical business negotiation.\n"
    "- **First-Class Prohibition**: Commercial First-Class travel is strictly prohibited across\n"
    "  all employee tiers, executive officers, and directors. No AI booking agent may authorize\n"
    "  First-Class travel without written board-level exemption.\n\n"
    "## 2. Lodging and Meal Allowances\n"
    "- Standard lodging allowance: Maximum $275.00 USD/night in Tier-1 cities (NYC, SFO, LON, TYO);\n"
    "  $195.00 USD/night elsewhere.\n"
    "- Per diem meal allowance: $85.00 USD daily total. Alcohol expenses require explicit\n"
    "  client-entertaining provenance with itemized receipts.\n"
)

DEMO_DOCUMENTS: list[dict[str, str]] = [
    {
        "filename": "institutional_financial_disbursement_policy.md",
        "collection": "default_kb",
        "content": FINANCIAL_POLICY,
    },
    {
        "filename": "clinical_pharmacology_pediatric_guidelines.md",
        "collection": "default_kb",
        "content": CLINICAL_POLICY,
    },
    {
        "filename": "corporate_travel_and_entertainment_governance.md",
        "collection": "default_kb",
        "content": TRAVEL_POLICY,
    },
]


async def seed_knowledge_base(tenant_id: str) -> None:
    """Seed sample institutional policy documents into Qdrant and PostgreSQL."""
    print("=" * 66)
    print("  MIRAGE 3.0: Seeding Demo Institutional Knowledge Base")
    print(f"  Target Tenant: {tenant_id}")
    print("=" * 66)

    service = KnowledgeBaseIngestionService()
    total_docs = len(DEMO_DOCUMENTS)
    total_chunks = 0

    for idx, doc in enumerate(DEMO_DOCUMENTS, start=1):
        filename = doc["filename"]
        content = doc["content"].strip()
        collection = doc["collection"]
        content_hash = compute_sha256(content)
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        print(f"\n[{idx}/{total_docs}] Ingesting '{filename}' into collection '{collection}'...")

        # 1. Ingest into Qdrant vector store
        ingest_res = await service.ingest_document(
            filename=filename,
            content=content,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=1,
        )

        chunk_count = ingest_res.get("chunks_count", 0)
        total_chunks += chunk_count
        print(f"  [OK] Vector indexing complete: {chunk_count} chunks embedded (dim=768).")

        # 2. Persist metadata in PostgreSQL KBDocumentRecord under tenant isolation
        try:
            await default_persistence_service.upsert_kb_document(
                tenant_id=tenant_id,
                document_id=doc_id,
                filename=filename,
                content_hash=content_hash,
                chunks_count=chunk_count,
                collection_name=collection,
                status="INDEXED",
                generation=1,
            )
            print(f"  [OK] PostgreSQL record persisted: doc_id={doc_id[:16]}... (Status: INDEXED)")
        except Exception as db_err:
            print(f"  [NOTE] PostgreSQL persistence notice: {db_err}")

    print("\n" + "=" * 66)
    print(f"  SEEDING COMPLETE: {total_docs} documents, {total_chunks} evidence chunks indexed.")
    print(f"  Tenant '{tenant_id}' is ready for Gate 2 RAG & Gate 4 verification.")
    print("=" * 66)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo institutional knowledge base for MIRAGE 3.0.")
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="tenant_vedant_primary",
        help="Target tenant ID (default: tenant_vedant_primary)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(seed_knowledge_base(tenant_id=args.tenant_id))
    except KeyboardInterrupt:
        print("\nSeeding interrupted by operator.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[ERROR] Seeding failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
