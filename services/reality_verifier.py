"""Gate 5 Outcome Assurance and Reality Verification Service for MIRAGE 3.0.

Implements Reality_Verification.md, Input_Output_Assurance.md §6, and AI_Action_Contract.md.
Confirms actual real-world state changes, enforcing epistemic observability boundaries,
monotonic outcome state transitions, cryptographic ActionContract binding, and SSRF defenses.
"""

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import time
import unicodedata
import urllib.parse
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpcore
import httpx
from fastapi import HTTPException, status
from sqlalchemy import select, text

from db import session as db_session
from db.models import ActionContract, AuditLogRecord, OutcomeVerificationRecord
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.action import ActionState
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeReconciliationResult,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)

logger = get_logger("reality_verifier")

# Completion claim patterns for Output <-> Outcome consistency reconciliation
_COMPLETION_ASSERTION_PATTERNS = (
    re.compile(
        r"\b(?:I (?:have )?(?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|cancelled|refunded|processed))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:transfer|payment|deletion|removal|deployment|action|execution|refund|"
        r"transaction|update|email|notification|message|item|items|batch|task|tasks|order|orders) "
        r"(?:has been |have been |was |were |is |are )"
        r"(?:completed|processed|executed|successful|finalized|done|sent|delivered))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:completed|processed|executed|finalized) "
        r"(?:the |all )?"
        r"(?:transfer|payment|deletion|deployment|action|refund|transaction|email|notification|items|batch|tasks))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:successfully (?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|refunded|processed|created|finished|completed))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|refunded|processed|created|finished|completed) successfully)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:has|have) (?:succeeded|been completed|been processed|been executed|"
        r"been sent|been deleted|been updated|been paid|been transferred))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:transfer|payment|transaction|wire|funds) (?:went through|has gone through|have gone through)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:funds|money|payment|wire) (?:have |has )?reached (?:the )?recipient\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:database|db|record|table) (?:has been |was |is )?updated\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:deployment|service|release|app) is (?:now )?live\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:the|first|second|this) )?(?:[a-z0-9_]+ )?"
        r"(?:transfer|payment|order|orders|action|transaction|operation|update|task) (?:has )?succeeded\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:it|this) has (?:now )?(?:completed|finished|succeeded)\b",
        re.IGNORECASE,
    ),
)


def _normalize_text(text: str) -> str:
    """Normalize unicode, whitespace, and typographic quotes to standard ASCII."""
    norm = unicodedata.normalize("NFKC", text)
    norm = re.sub(r"[\u200B-\u200D\uFEFF]", "", norm)
    norm = norm.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def _strip_quotes_and_citations(text: str) -> str:
    """Strip text inside quotation marks and markdown blockquotes so quotations are not treated as agent assertions."""
    # Strip markdown blockquotes
    text = re.sub(r"^\s*>.*$", "", text, flags=re.MULTILINE)
    # Strip double quotes
    text = re.sub(r'"[^"\n]*"', " ", text)
    # Strip single quotes around phrases
    text = re.sub(r"(?:^|\s)'(?:[^'\n]|'')*'(?:\s|$)", " ", text)
    return text


def _extract_clauses(text: str) -> list[str]:
    """Split text into independent clauses using sentence terminators and contrastive conjunctions."""
    sentences = re.split(r"[.!?;\n]+", text)
    clauses: list[str] = []
    contrastive_re = re.compile(
        r"\b(?:but|however|although|though|yet|nevertheless|whereas|while)\b", re.IGNORECASE
    )
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        subparts = contrastive_re.split(s)
        for part in subparts:
            part = part.strip()
            if part:
                clauses.append(part)
    return clauses


# Canonical monotonic outcome state machine transition rules
VALID_OUTCOME_TRANSITIONS: dict[OutcomeStatus, set[OutcomeStatus]] = {
    OutcomeStatus.UNKNOWN: {
        OutcomeStatus.UNKNOWN,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        OutcomeStatus.FAILED,
        OutcomeStatus.PARTIAL,
    },
    OutcomeStatus.ACKNOWLEDGED_UNVERIFIED: {
        OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.FAILED,
        OutcomeStatus.PARTIAL,
    },
    OutcomeStatus.PARTIAL: {
        OutcomeStatus.PARTIAL,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.FAILED,
    },
    OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED: {
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.SUCCESS_CONFIRMED,
    },
    OutcomeStatus.SUCCESS_CONFIRMED: {
        OutcomeStatus.SUCCESS_CONFIRMED,  # Terminal
    },
    OutcomeStatus.FAILED: {
        OutcomeStatus.FAILED,  # Terminal
    },
    OutcomeStatus.UNOBSERVABLE: {
        OutcomeStatus.UNOBSERVABLE,  # Terminal for OBS_BLIND
        OutcomeStatus.FAILED,
    },
}


class AdapterProbeResult:
    """Standardized result returned by an outcome verification adapter."""

    def __init__(
        self,
        observed_state: dict[str, Any],
        evidence_payload: dict[str, Any],
        discrepancies: list[str],
        is_simulated: bool,
        adapter_name: str,
        success_indicated: bool = True,
        reconciliation_notes: list[str] | None = None,
    ) -> None:
        self.observed_state = observed_state
        self.evidence_payload = evidence_payload
        self.discrepancies = discrepancies
        self.is_simulated = is_simulated
        self.adapter_name = adapter_name
        self.success_indicated = success_indicated
        self.reconciliation_notes = reconciliation_notes or []


class BaseOutcomeAdapter(ABC):
    """Abstract base class for pluggable reality verification adapters."""

    @abstractmethod
    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        """Execute reality verification probe against target system."""
        pass


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
        # Parse authorized table from action.target_resource
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
        # Validate that requested table matches authorized ActionContract target
        if authorized_table and requested_table:
            # Allow clean table match or table matching normalized parameters
            clean_auth = authorized_table.split("?")[0].strip()
            clean_req = requested_table.strip()
            if clean_auth and clean_req and clean_req.lower() != clean_auth.lower():
                # Check if authorized via parameters
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
            # Sanitize table identifier against SQL injection
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
                    # Enforce read-only transaction semantics
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
            # Evaluate action contract's observed_result
            observed_state = action.observed_result or {}
            evidence["source"] = "action_contract_observed_result"

        # Compare expected postconditions against observed state
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


class SafeAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend intercepting TCP socket connections to enforce IP allowlist at the connection boundary.

    Defends against Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding attacks where an adversarial
    domain returns a valid public IP during preflight check but resolves to an internal loopback
    or cloud metadata IP (e.g. 127.0.0.1, 169.254.169.254) at socket connection time.
    """

    def __init__(self, is_ip_allowed_fn: Callable[[str], bool], allow_local: bool = False) -> None:
        self._backend = httpcore.AnyIOBackend()
        self._is_ip_allowed_fn = is_ip_allowed_fn
        self._allow_local = allow_local

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        stream = await self._backend.connect_tcp(
            host, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )
        if not self._allow_local:
            server_addr = stream.get_extra_info("server_addr")
            if not server_addr:
                await stream.aclose()
                raise httpcore.ConnectError(
                    "SSRF / DNS rebinding security block: unable to verify peer address at connection boundary"
                )
            peer_ip = str(server_addr[0])
            if not self._is_ip_allowed_fn(peer_ip):
                await stream.aclose()
                raise httpcore.ConnectError(
                    f"SSRF / DNS rebinding security block: connection to peer IP '{peer_ip}' is forbidden"
                )
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        _ = (path, timeout, socket_options)
        raise httpcore.ConnectError("Unix domain sockets forbidden for outcome verification probes")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class SafeAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """Hardened AsyncHTTPTransport binding SafeAsyncNetworkBackend to prevent DNS rebinding and SSRF."""

    def __init__(
        self,
        is_ip_allowed_fn: Callable[[str], bool],
        allow_local: bool = False,
        **kwargs: Any,
    ) -> None:
        kwargs["trust_env"] = False
        super().__init__(**kwargs)
        backend = SafeAsyncNetworkBackend(is_ip_allowed_fn, allow_local=allow_local)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=self._pool._ssl_context,
            network_backend=backend,
            http1=True,
            http2=False,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
        )


class HttpResourceAdapter(BaseOutcomeAdapter):
    """Hardened HTTP GET/HEAD verification probe checking external REST endpoints.

    Enforces deep anti-SSRF defenses, DNS rebinding prevention, redirect re-validation,
    and ActionContract target host binding.
    """

    def _is_ip_allowed(self, host: str) -> bool:
        """SSRF defense: prevent connecting to private/loopback IP addresses or cloud metadata services."""
        clean_host = host.lower().strip()
        if (
            clean_host in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "169.254.169.254")
            or clean_host.endswith(".local")
            or clean_host.endswith(".internal")
        ):
            return False

        try:
            ip = ipaddress.ip_address(clean_host)
            return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
        except ValueError:
            # Resolve hostname to verify underlying IP against private ranges (A and AAAA)
            try:
                addr_info = socket.getaddrinfo(clean_host, None, proto=socket.IPPROTO_TCP)
                if not addr_info:
                    return False
                for _family, _, _, _, sockaddr in addr_info:
                    ip_str = sockaddr[0]
                    ip = ipaddress.ip_address(ip_str)
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                        return False
                return True
            except Exception:
                # Fail closed if resolution fails
                return False

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
            "adapter": "HttpResourceAdapter",
            "action_id": action.id,
            "tenant_id": tenant_id,
        }

        # 1. Target Resource Authorization
        target_url = config.get("verification_url") or (
            action.target_resource if action.target_resource.startswith("http") else None
        )
        if not target_url:
            discrepancies.append("HttpResourceAdapter requires 'verification_url' for readback verification")
            return AdapterProbeResult(
                observed_state=action.observed_result or {},
                evidence_payload={"note": "No verification_url provided"},
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        parsed = urllib.parse.urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            discrepancies.append(f"Unsupported URI scheme '{parsed.scheme}' (only http/https permitted)")
            return AdapterProbeResult(
                observed_state={},
                evidence_payload=evidence,
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        if parsed.username or parsed.password:
            discrepancies.append("URI contains userinfo credentials; rejected for security")
            return AdapterProbeResult(
                observed_state={},
                evidence_payload=evidence,
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        # ActionContract target resource binding
        if action.target_resource.startswith("http"):
            auth_parsed = urllib.parse.urlparse(action.target_resource)
            if auth_parsed.hostname and parsed.hostname and auth_parsed.hostname.lower() != parsed.hostname.lower():
                discrepancies.append(
                    f"Target resource mismatch: verification host '{parsed.hostname}' "
                    f"does not match authorized ActionContract host '{auth_parsed.hostname}'"
                )
                return AdapterProbeResult(
                    observed_state={},
                    evidence_payload=evidence,
                    discrepancies=discrepancies,
                    is_simulated=False,
                    adapter_name="HttpResourceAdapter",
                    success_indicated=False,
                )

        # Anti-SSRF check
        allow_local = config.get("allow_localhost_for_tests", False)
        if not allow_local and not self._is_ip_allowed(parsed.hostname or ""):
            discrepancies.append(
                f"SSRF violation: target host '{parsed.hostname}' is a forbidden private address"
            )
            return AdapterProbeResult(
                observed_state={},
                evidence_payload=evidence,
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        expected_status = config.get("expected_status", 200)

        # Execute HTTP probe with redirect control and socket-boundary SSRF/DNS-rebinding protection
        try:
            transport = SafeAsyncHTTPTransport(self._is_ip_allowed, allow_local=allow_local)
            async with httpx.AsyncClient(
                transport=transport,
                timeout=request.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = await client.get(target_url)
                evidence["http_status"] = resp.status_code
                evidence["headers"] = dict(resp.headers)
                observed_state["status_code"] = resp.status_code

                # Handle redirects explicitly
                if resp.is_redirect:
                    redir_loc = resp.headers.get("location")
                    if not redir_loc:
                        discrepancies.append("Redirect response missing Location header")
                    else:
                        redir_parsed = urllib.parse.urlparse(urllib.parse.urljoin(target_url, redir_loc))
                        if not allow_local and not self._is_ip_allowed(redir_parsed.hostname or ""):
                            discrepancies.append(
                                f"Redirect SSRF violation: redirect target '{redir_parsed.hostname}' "
                                f"is a forbidden address"
                            )
                        else:
                            # Re-verify redirect target with single bounded hop
                            resp = await client.get(redir_parsed.geturl())
                            evidence["redirect_http_status"] = resp.status_code
                            observed_state["status_code"] = resp.status_code

                if resp.status_code != expected_status:
                    discrepancies.append(
                        f"HTTP status code mismatch: expected {expected_status}, received {resp.status_code}"
                    )

                try:
                    body_json = resp.json()
                    observed_state["body"] = body_json
                    # Assert expected JSON fields
                    for key, val in expected.items():
                        if isinstance(body_json, dict) and body_json.get(key) != val:
                            discrepancies.append(
                                f"Response body mismatch on '{key}': expected '{val}', got '{body_json.get(key)}'"
                            )
                except Exception:
                    observed_state["body_text"] = resp.text[:500]

        except Exception as exc:
            discrepancies.append(f"HTTP verification probe failed: {exc!s}")

        return AdapterProbeResult(
            observed_state=observed_state,
            evidence_payload=evidence,
            discrepancies=discrepancies,
            is_simulated=False,
            adapter_name="HttpResourceAdapter",
            success_indicated=(len(discrepancies) == 0),
        )


class AsyncEventAdapter(BaseOutcomeAdapter):
    """Bounded exponential backoff polling adapter for eventual consistency (OBS_EVENTUAL)."""

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        expected = request.expected_postconditions
        config = request.adapter_config
        attempts = 0
        max_attempts = min(request.max_poll_attempts, 30)
        interval = max(request.poll_interval_seconds, 0.05)
        start_time = time.time()
        timeout = min(request.timeout_seconds, 60.0)

        observed_state: dict[str, Any] = {}
        discrepancies: list[str] = []
        evidence: dict[str, Any] = {
            "adapter": "AsyncEventAdapter",
            "action_id": action.id,
            "tenant_id": tenant_id,
            "poll_attempts": 0,
        }

        probe_fn = config.get("probe_callable")
        simulated_values = config.get("simulated_progression")
        is_sim = bool(simulated_values)

        matched = False

        while attempts < max_attempts and (time.time() - start_time) < timeout:
            attempts += 1
            evidence["poll_attempts"] = attempts

            if callable(probe_fn):
                try:
                    observed_state = await probe_fn(action, tenant_id)
                except Exception as exc:
                    observed_state = {"error": str(exc)}
            elif simulated_values and isinstance(simulated_values, list):
                idx = min(attempts - 1, len(simulated_values) - 1)
                observed_state = simulated_values[idx]
            else:
                observed_state = action.observed_result or {}

            # Check postconditions
            current_discrepancies: list[str] = []
            for key, expected_val in expected.items():
                if observed_state.get(key) != expected_val:
                    current_discrepancies.append(
                        f"Field '{key}' expected '{expected_val}', currently '{observed_state.get(key)}'"
                    )

            if not current_discrepancies:
                matched = True
                discrepancies = []
                break
            else:
                discrepancies = current_discrepancies

            # Exponential backoff jitter
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, 5.0)

        if not matched:
            discrepancies.append(
                f"Eventual consistency verification timed out after {attempts} attempts "
                f"({round(time.time() - start_time, 2)}s)"
            )

        return AdapterProbeResult(
            observed_state=observed_state,
            evidence_payload=evidence,
            discrepancies=discrepancies,
            is_simulated=is_sim,
            adapter_name="AsyncEventAdapter",
            success_indicated=matched,
            reconciliation_notes=[f"Polled {attempts} times before completion"],
        )


class SimulatedTestAdapter(BaseOutcomeAdapter):
    """Explicitly simulated test adapter for automated pipelines and testbeds.

    Enforces mandatory simulation provenance marking.
    NEVER satisfies production SUCCESS_CONFIRMED.
    """

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        config = request.adapter_config
        expected = request.expected_postconditions
        simulated_state = config.get("simulated_state", dict(expected))
        discrepancies: list[str] = []

        for key, expected_val in expected.items():
            if simulated_state.get(key) != expected_val:
                discrepancies.append(
                    f"Simulated mismatch on '{key}': expected '{expected_val}', observed '{simulated_state.get(key)}'"
                )

        return AdapterProbeResult(
            observed_state=simulated_state,
            evidence_payload={
                "simulated": True,
                "fixture": config.get("fixture_name", "default"),
                "action_id": action.id,
                "tenant_id": tenant_id,
                "disclaimer": "SIMULATED_TEST_VERIFIER_NOT_PRODUCTION",
            },
            discrepancies=discrepancies,
            is_simulated=True,
            adapter_name="SimulatedTestAdapter",
            success_indicated=(len(discrepancies) == 0),
            reconciliation_notes=[
                "Verified using SimulatedTestAdapter; "
                "simulation evidence CANNOT satisfy production physical verification."
            ],
        )


class RealityVerifierService:
    """Core Gate 5 Outcome Assurance engine validating external system state."""

    def __init__(self) -> None:
        self.adapters: dict[OutcomeVerifierType, BaseOutcomeAdapter] = {
            OutcomeVerifierType.DATABASE: DatabaseStateAdapter(),
            OutcomeVerifierType.HTTP_RESOURCE: HttpResourceAdapter(),
            OutcomeVerifierType.ASYNC_EVENT: AsyncEventAdapter(),
            OutcomeVerifierType.SIMULATED: SimulatedTestAdapter(),
        }

    def _validate_outcome_transition(self, current_status: OutcomeStatus, new_status: OutcomeStatus) -> None:
        """Enforce monotonic outcome state machine preventing status regression or illegal upgrades."""
        allowed = VALID_OUTCOME_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Illegal outcome transition: cannot transition from '{current_status.value}' "
                    f"to '{new_status.value}'. Transition not permitted by monotonic outcome state machine."
                ),
            )

    def _record_to_contract(self, record: OutcomeVerificationRecord) -> OutcomeVerificationContract:
        """Convert an authoritative database record to an immutable OutcomeVerificationContract.

        Enforces read-time cryptographic integrity check against the canonical payload.
        """
        canonical = (record.evidence_payload or {}).get("_canonical_payload")
        if canonical and isinstance(canonical, dict):
            # 1. Verify column integrity against canonical payload
            mismatches: list[str] = []
            if record.outcome_status != canonical.get("outcome_status"):
                mismatches.append(f"outcome_status ('{record.outcome_status}' != '{canonical.get('outcome_status')}')")
            if record.tenant_id != canonical.get("tenant_id"):
                mismatches.append(f"tenant_id ('{record.tenant_id}' != '{canonical.get('tenant_id')}')")
            if record.action_id != canonical.get("action_id"):
                mismatches.append(f"action_id ('{record.action_id}' != '{canonical.get('action_id')}')")
            if record.transaction_id != canonical.get("transaction_id"):
                mismatches.append(f"transaction_id ('{record.transaction_id}' != '{canonical.get('transaction_id')}')")
            if record.observability_class != canonical.get("observability_class"):
                mismatches.append(
                    f"observability_class ('{record.observability_class}' != '{canonical.get('observability_class')}')"
                )
            if abs(record.epistemic_confidence - float(canonical.get("epistemic_confidence", 0.0))) > 1e-5:
                stored_conf = record.epistemic_confidence
                expected_conf = canonical.get("epistemic_confidence")
                mismatches.append(f"epistemic_confidence ('{stored_conf}' != '{expected_conf}')")

            if mismatches:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cryptographic integrity violation: OutcomeVerificationRecord '{record.id}' "
                        f"tampered in storage. Divergences: {', '.join(mismatches)}"
                    ),
                )

            # 2. Recompute SHA-256 over canonical payload
            recomputed_hash = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if recomputed_hash != record.verification_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cryptographic integrity violation: OutcomeVerificationRecord '{record.id}' "
                        f"verification_hash mismatch. Stored: '{record.verification_hash}', "
                        f"Recomputed: '{recomputed_hash}'"
                    ),
                )

        verified_dt = (
            record.verified_at.isoformat()
            if hasattr(record.verified_at, "isoformat")
            else str(record.verified_at)
        )
        return OutcomeVerificationContract(
            outcome_id=record.id,
            transaction_id=record.transaction_id,
            action_id=record.action_id,
            tenant_id=record.tenant_id,
            observability_class=ObservabilityClass(record.observability_class),
            outcome_status=OutcomeStatus(record.outcome_status),
            epistemic_confidence=record.epistemic_confidence,
            verifier_adapter=record.verifier_adapter,
            is_simulated=record.is_simulated,
            expected_postconditions=record.expected_postconditions,
            observed_state=record.observed_state,
            discrepancies=record.discrepancies,
            evidence_payload=record.evidence_payload,
            reconciliation_notes=record.reconciliation_notes,
            verification_hash=record.verification_hash,
            idempotency_key=record.idempotency_key or "",
            target_environment=record.target_environment or "DEFAULT",
            contract_binding_hash=record.contract_binding_hash,
            schema_version="mirage.outcome.v1",
            verified_at=verified_dt,
        )

    async def verify_record_against_audit_trail(
        self,
        session: Any,
        record: OutcomeVerificationRecord,
        trusted_root_hash: str = "0" * 64,
        max_chain_depth: int = 500,
    ) -> OutcomeVerificationContract:
        """Verify OutcomeVerificationRecord integrity internally and against AuditLogRecord.

        Validates both self-consistency against canonical payload and external consistency
        against the append-only cryptographic AuditLogRecord trust anchor. Recursively traces
        the cryptographic chain back to trusted root (default genesis '0'*64). Fails closed (HTTP 409)
        if the trust anchor is missing, conflicting, tampered, or detached from the audit chain.
        """
        # 1. Internal canonical payload integrity and SHA-256 hash check
        contract = self._record_to_contract(record)

        # 2. External AuditLogRecord trust anchor lookup
        audit_stmt = (
            select(AuditLogRecord)
            .where(
                AuditLogRecord.tenant_id == record.tenant_id,
                AuditLogRecord.event_type == "GATE5_OUTCOME_VERIFIED",
            )
            .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
        )
        audit_records = (await session.execute(audit_stmt)).scalars().all()

        matching_audits: list[AuditLogRecord] = []
        for a in audit_records:
            payload = a.event_payload or {}
            # Strict correlation matching: NO loose fallback matching on action or transaction alone
            if payload.get("outcome_id") == record.id:
                matching_audits.append(a)

        # Fail closed: OutcomeVerificationRecord cannot be verified without an authoritative anchor
        if not matching_audits:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor missing: OutcomeVerificationRecord '{record.id}' has no corresponding "
                    f"authoritative AuditLogRecord trust anchor in tenant '{record.tenant_id}'."
                ),
            )

        if len(matching_audits) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Ambiguous or conflicting audit anchors detected: found {len(matching_audits)} matching "
                    f"AuditLogRecord entries for outcome '{record.id}'."
                ),
            )

        matching_audit = matching_audits[0]
        payload = matching_audit.event_payload or {}

        # 3. Unambiguous 4-way correlation check: outcome_id, action_id, tenant_id, transaction_id
        if payload.get("outcome_id") != record.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord '{matching_audit.entry_id}' "
                    f"outcome_id '{payload.get('outcome_id')}' does not match record '{record.id}'."
                ),
            )
        if not payload.get("action_id") or payload.get("action_id") != record.action_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord '{matching_audit.entry_id}' "
                    f"action_id '{payload.get('action_id')}' does not match record '{record.action_id}'."
                ),
            )
        if matching_audit.tenant_id != record.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord '{matching_audit.entry_id}' "
                    f"tenant_id '{matching_audit.tenant_id}' does not match record '{record.tenant_id}'."
                ),
            )
        # Strict transaction_id check on both record column and payload
        if matching_audit.transaction_id != record.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord column transaction_id "
                    f"'{matching_audit.transaction_id}' does not match record '{record.transaction_id}'."
                ),
            )
        if payload.get("transaction_id") != record.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord payload transaction_id "
                    f"'{payload.get('transaction_id')}' does not match record '{record.transaction_id}'."
                ),
            )

        # 4. Hash and Decision verification against audit record
        if matching_audit.response_hash != record.verification_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cryptographic audit trail divergence: OutcomeVerificationRecord '{record.id}' "
                    f"verification_hash '{record.verification_hash}' does not match immutable "
                    f"AuditLogRecord response_hash '{matching_audit.response_hash}'."
                ),
            )
        if matching_audit.decision != record.outcome_status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cryptographic audit trail divergence: OutcomeVerificationRecord '{record.id}' "
                    f"status '{record.outcome_status}' does not match immutable "
                    f"AuditLogRecord decision '{matching_audit.decision}'."
                ),
            )

        # 5. Cryptographic Chain Self-Integrity verification
        verified_at_val = payload.get("verified_at")
        if verified_at_val:
            expected_chain = compute_sha256(
                f"{matching_audit.prev_hash}:{matching_audit.entry_id}:{matching_audit.decision}:{verified_at_val}"
            )
            if matching_audit.chain_hash != expected_chain:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain corruption detected: AuditLogRecord '{matching_audit.entry_id}' "
                        f"chain_hash '{matching_audit.chain_hash}' does not match computed hash '{expected_chain}'."
                    ),
                )

        # 6. Full-Chain Recursive Validation Back to Trusted Root
        curr = matching_audit
        visited_hashes: set[str] = {curr.chain_hash}
        chain_depth = 0

        while curr.prev_hash != trusted_root_hash:
            chain_depth += 1
            if chain_depth > max_chain_depth:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain traversal exceeded max depth {max_chain_depth} "
                        f"without reaching trusted root '{trusted_root_hash}' for tenant '{record.tenant_id}'."
                    ),
                )
            if curr.prev_hash in visited_hashes:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain cyclic loop detected at hash '{curr.prev_hash}' "
                        f"for tenant '{record.tenant_id}'."
                    ),
                )

            pred_stmt = select(AuditLogRecord).where(
                AuditLogRecord.tenant_id == record.tenant_id,
                AuditLogRecord.chain_hash == curr.prev_hash,
            )
            pred_record = (await session.execute(pred_stmt)).scalar_one_or_none()
            if not pred_record:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain broken linkage: predecessor block with chain_hash '{curr.prev_hash}' "
                        f"not found in audit trail for tenant '{record.tenant_id}' (traversed depth {chain_depth}). "
                        f"Chain does not anchor to trusted root '{trusted_root_hash}'."
                    ),
                )

            if pred_record.chain_hash in visited_hashes or pred_record.prev_hash in visited_hashes:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain cyclic loop detected at ancestor '{pred_record.entry_id}' "
                        f"for tenant '{record.tenant_id}'."
                    ),
                )

            # Monotonicity check
            if (
                pred_record.created_at
                and curr.created_at
                and pred_record.created_at > curr.created_at
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain reordering detected: ancestor block '{pred_record.entry_id}' timestamp "
                        f"'{pred_record.created_at}' is later than descendant '{curr.entry_id}' timestamp "
                        f"'{curr.created_at}'."
                    ),
                )

            # Predecessor self-integrity check
            p_payload = pred_record.event_payload or {}
            p_verified_at = p_payload.get("verified_at")
            if p_verified_at and pred_record.decision:
                expected_p_hash = compute_sha256(
                    f"{pred_record.prev_hash}:{pred_record.entry_id}:{pred_record.decision}:{p_verified_at}"
                )
                if pred_record.chain_hash != expected_p_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Audit chain corruption detected at ancestor '{pred_record.entry_id}': "
                            f"chain_hash '{pred_record.chain_hash}' does not match computed hash '{expected_p_hash}'."
                        ),
                    )

            visited_hashes.add(curr.prev_hash)
            curr = pred_record

        return contract

    async def verify_action_outcome(
        self,
        request: OutcomeVerificationRequest,
        auth: AuthContext,
    ) -> OutcomeVerificationContract:
        """Execute reality verification for an executed ActionContract."""
        # 1. Authorization: Only SUPER_ADMIN, TENANT_ADMIN, OPERATOR, API_CLIENT may trigger reality verification
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR, Role.API_CLIENT):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{auth.role.value}' is not authorized to trigger reality verification probes.",
            )

        outcome_id = f"outc_{uuid.uuid4().hex[:12]}"
        reconciliation_notes: list[str] = []
        idempotency_key = request.idempotency_key or f"idem_outc_{request.action_id}_{request.verifier_type.value}"

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            # 2. Fetch and validate ActionContract under tenant boundary with row-level lock
            stmt = (
                select(ActionContract)
                .where(
                    ActionContract.id == request.action_id,
                    ActionContract.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            action = (await session.execute(stmt)).scalar_one_or_none()
            if not action:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"ActionContract '{request.action_id}' not found for tenant '{auth.tenant_id}'",
                )

            if action.transaction_id != request.transaction_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"ActionContract transaction mismatch: contract belongs to '{action.transaction_id}', "
                        f"request specified '{request.transaction_id}'"
                    ),
                )

            # 3. Action Execution State Invariant:
            # Action MUST be COMPLETED or EXECUTED. In-flight or proposed actions CANNOT be verified.
            if action.state not in (ActionState.COMPLETED.value, "EXECUTED"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot verify unexecuted action: ActionContract '{action.id}' is in state '{action.state}'. "
                        f"Only COMPLETED or EXECUTED actions may be verified."
                    ),
                )

            # 4. Check for existing outcome record for idempotency and monotonic state transitions
            existing_stmt = (
                select(OutcomeVerificationRecord)
                .where(
                    OutcomeVerificationRecord.tenant_id == auth.tenant_id,
                    OutcomeVerificationRecord.action_id == action.id,
                )
                .order_by(OutcomeVerificationRecord.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            raw_existing = (await session.execute(existing_stmt)).scalar_one_or_none()
            existing_record = raw_existing if isinstance(raw_existing, OutcomeVerificationRecord) else None
            if existing_record:
                # Idempotency check: if existing is terminal or matches idempotency key
                if existing_record.idempotency_key == idempotency_key and existing_record.outcome_status in (
                    OutcomeStatus.SUCCESS_CONFIRMED.value,
                    OutcomeStatus.FAILED.value,
                ):
                    return self._record_to_contract(existing_record)

            # 5. Environment Binding
            target_env = "DEFAULT"
            if isinstance(action.blast_radius, dict):
                target_env = action.blast_radius.get("target_environment", "DEFAULT")

            req_env = request.adapter_config.get("environment")
            if req_env and req_env.upper() != target_env.upper():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Environment mismatch: probe requested environment '{req_env}' does not match "
                        f"authorized ActionContract target_environment '{target_env}'"
                    ),
                )

            # 6. Production Simulation Check
            settings = get_settings()
            if (
                request.verifier_type == OutcomeVerifierType.SIMULATED
                and (settings.environment.value == "production" or target_env.upper() == "PROD")
                and not request.adapter_config.get("allow_simulated_for_test", False)
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SimulatedTestAdapter is prohibited for production environment verification.",
                )

            # 7. Postconditions Binding Validation
            # Merge contract postconditions with request postconditions
            authoritative_postconditions: dict[str, Any] = {}
            if action.postconditions and isinstance(action.postconditions, list):
                for p in action.postconditions:
                    if isinstance(p, dict) and "target" in p:
                        authoritative_postconditions[p["target"]] = p.get("expected_value")

            # Check if request expected postconditions contradict contract postconditions
            for k, req_v in request.expected_postconditions.items():
                if k in authoritative_postconditions and authoritative_postconditions[k] != req_v:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Postcondition mismatch: requested postcondition '{k}={req_v}' contradicts "
                            f"ActionContract postcondition '{authoritative_postconditions[k]}'"
                        ),
                    )

            effective_postconditions = {**authoritative_postconditions, **request.expected_postconditions}
            effective_request = request.model_copy(update={"expected_postconditions": effective_postconditions})

            # 8. Select Adapter and execute probe
            adapter = self.adapters.get(request.verifier_type)
            if not adapter:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported outcome verifier type '{request.verifier_type}'",
                )

            probe_result = await adapter.verify(action, effective_request, auth.tenant_id)
            reconciliation_notes.extend(probe_result.reconciliation_notes)

            # 9. Determine OutcomeStatus and Epistemic Confidence
            target_scheme = ""
            if action.target_resource:
                target_scheme = (
                    action.target_resource.split("://")[0].lower()
                    if "://" in action.target_resource
                    else action.target_resource.split(":")[0].lower()
                )
            is_blind_sink = target_scheme in ("udp", "syslog", "mailto", "smtp", "blackhole", "devnull", "sink")

            obs_class = request.observability_class
            discrepancies = probe_result.discrepancies

            # Enforce authoritative blind sink override: client cannot forge OBS_DIRECT on write-only sinks
            if is_blind_sink and obs_class != ObservabilityClass.OBS_BLIND:
                obs_class = ObservabilityClass.OBS_BLIND
                reconciliation_notes.append(
                    f"Target resource '{action.target_resource}' is an unobservable write-only sink ({target_scheme}). "
                    f"Client observability class '{request.observability_class.value}' "
                    "authoritatively downgraded to OBS_BLIND."
                )

            if obs_class == ObservabilityClass.OBS_BLIND:
                outcome_status = OutcomeStatus.UNOBSERVABLE
                epistemic_confidence = 0.0
                reconciliation_notes.append(
                    "Target resource is OBS_BLIND (write-only sink). No readback channel exists. "
                    "Epistemic confidence is strictly 0.0."
                )

            elif obs_class == ObservabilityClass.OBS_INFERRED:
                outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
                epistemic_confidence = 0.50
                reconciliation_notes.append(
                    "Target resource is OBS_INFERRED (transport-acknowledged only). "
                    "Actual postconditions at destination sink cannot be directly inspected by MIRAGE."
                )

            elif obs_class == ObservabilityClass.OBS_DIRECT:
                # Epistemic Invariant: void postconditions assertion CANNOT produce SUCCESS_CONFIRMED
                if len(effective_postconditions) == 0:
                    outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
                    epistemic_confidence = 0.50
                    reconciliation_notes.append(
                        "Void postcondition assertion: zero expected postconditions were specified. "
                        "SUCCESS_CONFIRMED requires authoritative postcondition state verification. "
                        "Status downgraded to ACKNOWLEDGED_UNVERIFIED."
                    )
                elif probe_result.is_simulated:
                    # Simulation evidence NEVER satisfies production SUCCESS_CONFIRMED!
                    if discrepancies:
                        outcome_status = OutcomeStatus.FAILED
                        epistemic_confidence = 0.95
                    else:
                        outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
                        epistemic_confidence = 0.50
                        reconciliation_notes.append(
                            "Probe executed using SimulatedTestAdapter; physical reality unverified. "
                            "Cannot be awarded SUCCESS_CONFIRMED."
                        )
                elif discrepancies:
                    if len(discrepancies) < len(effective_postconditions) and len(effective_postconditions) > 1:
                        outcome_status = OutcomeStatus.PARTIAL
                        epistemic_confidence = 0.85
                    else:
                        outcome_status = OutcomeStatus.FAILED
                        epistemic_confidence = 0.95
                else:
                    outcome_status = OutcomeStatus.SUCCESS_CONFIRMED
                    epistemic_confidence = 1.00

            elif obs_class == ObservabilityClass.OBS_EVENTUAL:
                if len(effective_postconditions) == 0:
                    outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
                    epistemic_confidence = 0.50
                    reconciliation_notes.append(
                        "Void postcondition assertion: zero expected postconditions were specified. "
                        "Cannot award SUCCESS_EVENTUALLY_OBSERVED without verified postconditions."
                    )
                elif probe_result.success_indicated and not discrepancies:
                    outcome_status = OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED
                    epistemic_confidence = 0.95
                elif "timed out" in " ".join(discrepancies).lower():
                    outcome_status = OutcomeStatus.UNKNOWN
                    epistemic_confidence = 0.0
                    reconciliation_notes.append(
                        "Eventual consistency polling timed out without observing stable target state."
                    )
                else:
                    outcome_status = OutcomeStatus.FAILED
                    epistemic_confidence = 0.90

            else:
                outcome_status = OutcomeStatus.UNKNOWN
                epistemic_confidence = 0.0

            # 10. Monotonic state transition enforcement against existing record
            if existing_record:
                curr_status = OutcomeStatus(existing_record.outcome_status)
                self._validate_outcome_transition(curr_status, outcome_status)

            # 11. Canonical Cryptographic Verification Hash
            observed_state_bytes = json.dumps(
                probe_result.observed_state, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            observed_state_hash = hashlib.sha256(observed_state_bytes).hexdigest()
            verified_at_dt = datetime.now(UTC)
            verified_at_iso = verified_at_dt.isoformat()

            canonical_payload = {
                "schema_version": "mirage.outcome.v1",
                "tenant_id": auth.tenant_id,
                "transaction_id": action.transaction_id,
                "action_id": action.id,
                "contract_binding_hash": action.parameters_hash,
                "tool_name": action.tool_name,
                "target_resource": action.target_resource,
                "required_capability": action.required_capability,
                "target_environment": target_env,
                "observability_class": obs_class.value,
                "outcome_status": outcome_status.value,
                "epistemic_confidence": epistemic_confidence,
                "verifier_adapter": probe_result.adapter_name,
                "is_simulated": probe_result.is_simulated,
                "expected_postconditions": effective_postconditions,
                "observed_state_hash": observed_state_hash,
                "verified_at": verified_at_iso,
                "idempotency_key": idempotency_key,
            }
            canonical_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            verification_hash = hashlib.sha256(canonical_bytes).hexdigest()

            evidence_payload = {
                **probe_result.evidence_payload,
                "_canonical_payload": canonical_payload,
            }

            # 12. Upsert OutcomeVerificationRecord
            if existing_record:
                record = existing_record
                record.observability_class = obs_class.value
                record.outcome_status = outcome_status.value
                record.epistemic_confidence = epistemic_confidence
                record.verifier_adapter = probe_result.adapter_name
                record.is_simulated = probe_result.is_simulated
                record.expected_postconditions = effective_postconditions
                record.observed_state = probe_result.observed_state
                record.discrepancies = discrepancies
                record.evidence_payload = evidence_payload
                record.reconciliation_notes = reconciliation_notes
                record.verification_hash = verification_hash
                record.idempotency_key = idempotency_key
                record.target_environment = target_env
                record.contract_binding_hash = action.parameters_hash
                record.verified_at = verified_at_dt
            else:
                record = OutcomeVerificationRecord(
                    id=outcome_id,
                    tenant_id=auth.tenant_id,
                    transaction_id=request.transaction_id,
                    action_id=request.action_id,
                    observability_class=obs_class.value,
                    outcome_status=outcome_status.value,
                    epistemic_confidence=epistemic_confidence,
                    verifier_adapter=probe_result.adapter_name,
                    is_simulated=probe_result.is_simulated,
                    expected_postconditions=effective_postconditions,
                    observed_state=probe_result.observed_state,
                    discrepancies=discrepancies,
                    evidence_payload=evidence_payload,
                    reconciliation_notes=reconciliation_notes,
                    verification_hash=verification_hash,
                    idempotency_key=idempotency_key,
                    target_environment=target_env,
                    contract_binding_hash=action.parameters_hash,
                    created_at=verified_at_dt,
                    verified_at=verified_at_dt,
                )
                session.add(record)

            # 13. Audit Trail Recording with cryptographic chain linkage
            latest_audit = await session.execute(
                select(AuditLogRecord.chain_hash)
                .where(AuditLogRecord.tenant_id == auth.tenant_id)
                .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
                .limit(1)
            )
            prev_chain_hash = latest_audit.scalar_one_or_none() or "0" * 64
            entry_id = f"aud_{uuid.uuid4().hex}"
            chain_hash = compute_sha256(f"{prev_chain_hash}:{entry_id}:{outcome_status.value}:{verified_at_iso}")

            audit_entry = AuditLogRecord(
                entry_id=entry_id,
                tenant_id=auth.tenant_id,
                session_id=request.transaction_id,
                trace_id="gate5-outcome",
                prompt_hash="0" * 64,
                response_hash=verification_hash,
                hrs_score=round(1.0 - epistemic_confidence, 4),
                risk_tier="LOW" if epistemic_confidence > 0.8 else "MEDIUM",
                claims_count=len(effective_postconditions),
                claims_summary=[],
                correction_applied=False,
                event_type="GATE5_OUTCOME_VERIFIED",
                actor_identity_id=auth.identity_id or "system_actor",
                transaction_id=request.transaction_id,
                decision=outcome_status.value,
                policy_reference=None,
                capability_id=action.required_capability,
                reason=f"Observability: {obs_class.value}, Adapter: {probe_result.adapter_name}",
                event_payload={
                    "outcome_id": record.id,
                    "action_id": request.action_id,
                    "transaction_id": request.transaction_id,
                    "observability_class": obs_class.value,
                    "outcome_status": outcome_status.value,
                    "epistemic_confidence": epistemic_confidence,
                    "adapter": probe_result.adapter_name,
                    "is_simulated": probe_result.is_simulated,
                    "discrepancies": discrepancies,
                    "target_environment": target_env,
                    "idempotency_key": idempotency_key,
                    "verified_at": verified_at_iso,
                },
                prev_hash=prev_chain_hash,
                chain_hash=chain_hash,
                created_at=verified_at_dt,
            )
            session.add(audit_entry)

            logger.info(
                "Gate 5 Outcome Verification completed",
                outcome_id=record.id,
                action_id=request.action_id,
                tenant_id=auth.tenant_id,
                observability=obs_class.value,
                status=outcome_status.value,
                confidence=epistemic_confidence,
                adapter=probe_result.adapter_name,
                discrepancies=len(discrepancies),
            )

            return self._record_to_contract(record)

    def reconcile_output_with_outcome(
        self,
        response_text: str,
        outcome_contract: OutcomeVerificationContract,
        transaction_id: str | None = None,
        action_id: str | None = None,
        auth_tenant_id: str | None = None,
    ) -> OutcomeReconciliationResult:
        """Verify Output <-> Outcome consistency: prevent models from falsely claiming verified success."""
        # 1. Tenant boundary check
        if auth_tenant_id is not None:
            if not auth_tenant_id.strip() or outcome_contract.tenant_id != auth_tenant_id.strip():
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        f"Cross-tenant outcome violation: outcome tenant '{outcome_contract.tenant_id}' "
                        f"does not match authenticated tenant '{auth_tenant_id}'"
                    ],
                    recommended_disposition="REJECT",
                )

        # 2. Transaction and Action correlation check
        if transaction_id is not None:
            if not transaction_id.strip() or outcome_contract.transaction_id != transaction_id.strip():
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        f"Transaction correlation mismatch: outcome belongs to '{outcome_contract.transaction_id}', "
                        f"caller specified '{transaction_id}'"
                    ],
                    recommended_disposition="REJECT",
                )

        if action_id is not None:
            if not action_id.strip() or outcome_contract.action_id != action_id.strip():
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        f"Action correlation mismatch: outcome belongs to action '{outcome_contract.action_id}', "
                        f"caller specified '{action_id}'"
                    ],
                    recommended_disposition="REJECT",
                )

        # 3. Clause-aware normalization and polarity evaluation
        norm_text = _normalize_text(response_text)
        unquoted = _strip_quotes_and_citations(norm_text)
        clauses = _extract_clauses(unquoted)

        claims_completion = False
        has_explicit_failure = False
        conflict_reasons: list[str] = []

        for clause in clauses:
            clause_lower = clause.lower()
            if any(
                u in clause_lower
                for u in [
                    "cannot confirm",
                    "could not confirm",
                    "unclear whether",
                    "unable to confirm",
                    "unable to verify",
                    "not confirmed",
                    "failed to confirm",
                    "no confirmation that",
                    "no evidence that",
                ]
            ):
                continue

            if any(
                f in clause_lower
                for f in [
                    "operation failed",
                    "action failed",
                    "failed, so",
                    "failed to execute",
                    "execution failed",
                    "failed completely",
                    "was unsuccessful",
                    "did not succeed",
                ]
            ):
                has_explicit_failure = True

            for pat in _COMPLETION_ASSERTION_PATTERNS:
                for m in pat.finditer(clause):
                    start_idx = max(0, m.start() - 35)
                    prefix = clause[start_idx : m.start()].lower()
                    negated = any(
                        neg in prefix
                        for neg in [
                            "not ",
                            "never ",
                            "failed to ",
                            "unable to ",
                            "could not ",
                            "did not ",
                            "was not ",
                            "were not ",
                            "has not ",
                            "have not ",
                            "is not ",
                            "are not ",
                        ]
                    )
                    if not negated:
                        claims_completion = True
                        break
                if claims_completion:
                    break

        status_val = outcome_contract.outcome_status

        # If the output does NOT assert completion:
        if not claims_completion:
            # If the verified outcome was FAILED, UNKNOWN, UNOBSERVABLE, PARTIAL, or ACKNOWLEDGED_UNVERIFIED:
            # The model is honest and refrains from false success claims.
            if status_val in (
                OutcomeStatus.FAILED,
                OutcomeStatus.UNKNOWN,
                OutcomeStatus.UNOBSERVABLE,
                OutcomeStatus.PARTIAL,
                OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
            ):
                return OutcomeReconciliationResult(
                    is_consistent=True,
                    epistemic_conflict_detected=False,
                    conflict_reasons=[],
                    recommended_disposition="PERMIT",
                )

            # If the verified outcome was confirmed success, but output explicitly asserted failure:
            if status_val in (OutcomeStatus.SUCCESS_CONFIRMED, OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED):
                if has_explicit_failure:
                    return OutcomeReconciliationResult(
                        is_consistent=False,
                        epistemic_conflict_detected=True,
                        conflict_reasons=[
                            "Contradiction: Output claims action failure, but Gate 5 reality verification "
                            "confirmed successful state transition."
                        ],
                        recommended_disposition="REWRITE_WITH_CAVEAT",
                    )
                # Output expressed uncertainty without false claims
                return OutcomeReconciliationResult(
                    is_consistent=True,
                    epistemic_conflict_detected=False,
                    conflict_reasons=[],
                    recommended_disposition="PERMIT",
                )

        # Output DOES claim completion:
        # 4. Simulation Check: Simulated evidence NEVER justifies claims of physical success
        if outcome_contract.is_simulated:
            conflict_reasons.append(
                "Epistemic Invariant Violation: Output asserts real-world success, but verification evidence "
                "is simulated (SimulatedTestAdapter). Simulation evidence cannot prove physical real-world execution."
            )
            return OutcomeReconciliationResult(
                is_consistent=False,
                epistemic_conflict_detected=True,
                conflict_reasons=conflict_reasons,
                recommended_disposition="REWRITE_WITH_CAVEAT",
            )

        # 5. Confirmed Success Checks
        if status_val in (OutcomeStatus.SUCCESS_CONFIRMED, OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED):
            return OutcomeReconciliationResult(
                is_consistent=True,
                epistemic_conflict_detected=False,
                conflict_reasons=[],
                recommended_disposition="PERMIT",
            )

        # 6. Partial, Failed, Unobservable, Inferred, Unknown Handling
        conflict_msg = (
            f"Epistemic Invariant Violation: Output claims successful action completion, but Gate 5 "
            f"reality status is '{status_val.value}' with confidence {outcome_contract.epistemic_confidence}. "
        )
        if status_val == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED:
            conflict_msg += "Transport acknowledgment alone does not prove destination state change."
        elif status_val == OutcomeStatus.UNOBSERVABLE:
            conflict_msg += "Target resource is write-only/unobservable; physical state confirmation is impossible."
        elif status_val == OutcomeStatus.FAILED:
            conflict_msg += "State verification observed explicit invariant failure."
        elif status_val == OutcomeStatus.PARTIAL:
            conflict_msg += (
                "Outcome is PARTIAL: subset of actions failed in batch; output cannot claim complete success."
            )
        elif status_val == OutcomeStatus.UNKNOWN:
            conflict_msg += "State verification timed out or was indeterminate."

        conflict_reasons.append(conflict_msg)

        disposition = "REJECT" if status_val == OutcomeStatus.FAILED else "REWRITE_WITH_CAVEAT"
        return OutcomeReconciliationResult(
            is_consistent=False,
            epistemic_conflict_detected=True,
            conflict_reasons=conflict_reasons,
            recommended_disposition=disposition,
        )

    def propose_compensating_action(self, action: ActionContract) -> None:
        """In accordance with MIRAGE 3.0 Gate 5 Invariants:

        Gate 5 must NEVER execute a recovery or compensating action directly.
        Any compensating action MUST be submitted as a new governed Gate 3 action contract
        evaluated through ActionGovernorService.propose_and_authorize_action.
        """
        raise NotImplementedError(
            f"Gate 5 cannot execute compensating action for '{action.id}' directly. "
            "Compensating actions must be proposed and authorized through Gate 3 (Action Governor)."
        )


reality_verifier_service = RealityVerifierService()
