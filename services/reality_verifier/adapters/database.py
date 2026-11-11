"""Direct synchronous SQL/database inspection adapter (OBS_DIRECT).

Authoritative Specs: Reality_Verification.md §3.1.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from sqlalchemy import text

from db import session as db_session
from db.models import ActionContract
from shared.logging import get_logger
from shared.schemas.outcome import OutcomeVerificationRequest

from .base import AdapterProbeResult, BaseOutcomeAdapter

logger = get_logger("reality_verifier.database")


class DatabaseStateAdapter(BaseOutcomeAdapter):
    """Direct synchronous SQL/database inspection adapter (OBS_DIRECT)."""

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        config = request.adapter_config
        expected = request.expected_postconditions
        discrepancies: list[str] = []
        observed_state: dict[str, Any] = {}
        evidence: dict[str, Any] = {
            "adapter": "DatabaseStateAdapter",
            "action_id": action.id,
            "tenant_id": tenant_id,
        }

        # 1. Authoritative Target Resource Validation
        target_res = action.target_resource
        authorized_table: str | None = None
        if "://" in target_res:
            parsed = urllib.parse.urlparse(target_res)
            res_path = parsed.path.strip("/")
            parts = res_path.split("/") if res_path else []
            authorized_table = parts[-1] if parts and parts[-1] else (parsed.netloc or None)
        elif "/" in target_res:
            authorized_table = target_res.split("/")[-1]
        else:
            authorized_table = target_res

        requested_table = config.get("table_name")
        if authorized_table and requested_table:
            clean_auth = authorized_table.split("?")[0].strip()
            clean_req = requested_table.strip()
            if clean_auth and clean_req and clean_req.lower() != clean_auth.lower():
                param_table = action.normalized_parameters.get("table") or action.normalized_parameters.get("db_table")
                if not param_table or str(param_table).strip().lower() != clean_req.lower():
                    discrepancies.append(
                        f"Target resource violation: probe table '{clean_req}' does not match "
                        f"authorized ActionContract target '{clean_auth}'"
                    )
                    return AdapterProbeResult(
                        observed_state={},
                        evidence_payload=evidence,
                        discrepancies=discrepancies,
                        is_simulated=False,
                        adapter_name="DatabaseStateAdapter",
                        success_indicated=False,
                    )

        table_name = requested_table or authorized_table
        record_id = (
            config.get("record_id")
            or action.normalized_parameters.get("id")
            or action.normalized_parameters.get("record_id")
        )

        if table_name and record_id:
            clean_tbl = str(table_name).split("?")[0].strip()
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", clean_tbl):
                discrepancies.append(f"Invalid table identifier '{table_name}': SQL injection blocked")
                return AdapterProbeResult(
                    observed_state={},
                    evidence_payload=evidence,
                    discrepancies=discrepancies,
                    is_simulated=False,
                    adapter_name="DatabaseStateAdapter",
                    success_indicated=False,
                )

            async with db_session.get_tenant_session(tenant_id) as session:
                try:
                    await session.execute(text("SET TRANSACTION READ ONLY"))
                    query = text(f"SELECT * FROM {clean_tbl} WHERE id = :rid")
                    res = (await session.execute(query, {"rid": str(record_id)})).mappings().one_or_none()
                    if res is None:
                        discrepancies.append(f"Target record '{record_id}' not found in table '{clean_tbl}'")
                    else:
                        observed_state = dict(res)
                        evidence["raw_record_keys"] = list(observed_state.keys())
                except Exception as exc:
                    logger.warning("Database adapter probe failed", error=str(exc))
                    discrepancies.append(f"Database query error: {exc!s}")
        else:
            observed_state = action.observed_result or {}
            evidence["source"] = "action_contract_observed_result"

        for key, expected_val in expected.items():
            actual_val = observed_state.get(key)
            if actual_val is None:
                discrepancies.append(f"Expected field '{key}' not present in observed state")
            elif actual_val != expected_val:
                discrepancies.append(
                    f"Postcondition mismatch on '{key}': expected '{expected_val}', observed '{actual_val}'"
                )

        return AdapterProbeResult(
            observed_state=observed_state,
            evidence_payload=evidence,
            discrepancies=discrepancies,
            is_simulated=False,
            adapter_name="DatabaseStateAdapter",
            success_indicated=(len(discrepancies) == 0),
        )
