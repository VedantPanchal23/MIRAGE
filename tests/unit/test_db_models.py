"""Unit tests for SQLAlchemy database models and schema definitions."""

import pytest

from db.session import Base


@pytest.mark.unit
class TestDatabaseModels:
    def test_tables_registered(self) -> None:
        table_names = set(Base.metadata.tables.keys())
        expected = {"tenants", "verification_sessions", "claims", "audit_logs"}
        assert expected.issubset(table_names)

    def test_tenant_columns(self) -> None:
        table = Base.metadata.tables["tenants"]
        cols = {c.name for c in table.columns}
        assert {"id", "name", "api_key_hash", "tier", "scs_enabled", "pii_detection_enabled", "created_at"}.issubset(
            cols
        )

    def test_verification_session_columns(self) -> None:
        table = Base.metadata.tables["verification_sessions"]
        cols = {c.name for c in table.columns}
        assert {
            "session_id",
            "tenant_id",
            "trace_id",
            "model_id",
            "prompt_hash",
            "response_hash",
            "hrs_score",
            "risk_tier",
            "correction_applied",
            "created_at",
        }.issubset(cols)

    def test_claims_columns(self) -> None:
        table = Base.metadata.tables["claims"]
        cols = {c.name for c in table.columns}
        assert {
            "id",
            "session_id",
            "tenant_id",
            "claim_text",
            "claim_type",
            "criticality",
            "criticality_weight",
            "rav_score",
            "scs_score",
            "nli_score",
            "ics_score",
            "vgs_score",
            "risk_score",
            "status",
            "signal_attribution",
            "created_at",
        }.issubset(cols)

    def test_audit_logs_columns(self) -> None:
        table = Base.metadata.tables["audit_logs"]
        cols = {c.name for c in table.columns}
        assert {
            "entry_id",
            "tenant_id",
            "session_id",
            "trace_id",
            "prompt_hash",
            "response_hash",
            "hrs_score",
            "risk_tier",
            "claims_count",
            "claims_summary",
            "correction_applied",
            "prev_hash",
            "chain_hash",
            "created_at",
        }.issubset(cols)
