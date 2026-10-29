"""Unit tests for MIRAGE 3.0 Regulatory Compliance Dossier Service."""

import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.compliance_dossier_service import ComplianceDossierService


@pytest.mark.asyncio
async def test_generate_compliance_dossier_zip() -> None:
    """Test generating signed regulatory compliance dossier zip package."""
    service = ComplianceDossierService()
    mock_session = AsyncMock()

    mock_chain_res = {
        "valid": True,
        "total_records_verified": 10,
        "head_chain_hash": "head_hash_abc",
        "chain_status": "VERIFIED_UNBROKEN",
        "defects": [],
    }

    mock_audit_res = MagicMock()
    mock_audit_res.scalars.return_value.all.return_value = []

    mock_approval_res = MagicMock()
    mock_approval_res.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [mock_audit_res, mock_approval_res]

    with patch("services.audit_ledger.AuditLedgerService.verify_chain", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_chain_res

        zip_bytes = await service.generate_dossier_zip(session=mock_session, tenant_id="tenant_audit_test")

        assert len(zip_bytes) > 0

        # Unpack and verify zip contents
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            file_names = zf.namelist()
            assert "audit_ledger_chain.jsonl" in file_names
            assert "cryptographic_verification.json" in file_names
            assert "human_oversight_decisions.json" in file_names
            assert "rls_isolation_attestation.json" in file_names
            assert "COMPLIANCE_SUMMARY.md" in file_names

            # Verify crypto verification JSON
            crypto_json = json.loads(zf.read("cryptographic_verification.json").decode("utf-8"))
            assert crypto_json["valid"] is True
            assert crypto_json["entries_verified"] == 10
            assert crypto_json["head_chain_hash"] == "head_hash_abc"

            # Verify RLS isolation attestation
            rls_json = json.loads(zf.read("rls_isolation_attestation.json").decode("utf-8"))
            assert rls_json["tenant_id"] == "tenant_audit_test"
            assert rls_json["database_engine"] == "PostgreSQL 16"
            assert rls_json["status"] == "ENFORCED"

            # Verify markdown summary
            md_text = zf.read("COMPLIANCE_SUMMARY.md").decode("utf-8")
            assert "tenant_audit_test" in md_text
            assert "EU AI Act" in md_text
