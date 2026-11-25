# ADR-0009: Enterprise Hardening for Billing, Identity, WORM Anchoring, Shadow Mode, and Privacy

- **Title:** Enterprise Hardening for Billing, Identity, WORM Anchoring, Shadow Mode, and Privacy
- **Status:** Accepted
- **Date:** 2026-11-25

---

## 1. Context

A cross-functional readiness audit of MIRAGE 3.0 identified critical security, operational, and governance gaps when deploying as a commercial multi-tenant platform:
1. Payment webhooks (`POST /v1/billing/webhook`) lacked mandatory cryptographic signature verification (`Stripe-Signature` / `X-Razorpay-Signature`), Stripe checkout/verification returned synthetic values without upstream settlement checks, and Razorpay signature bypass prefixes were not restricted strictly to `EnvironmentType.TEST`.
2. `Settings` embedded non-empty default SMTP credentials, and tenant administrators lacked `/v1/auth/users` RBAC team management endpoints and OIDC verification configuration hooks.
3. External audit anchoring (`services/audit_anchor.py`) supported only local disk JSONL files (`FileAuditAnchorBackend`), leaving `RSK-ANCHOR-02` without a native S3 Object Lock WORM backend implementation.
4. SDK wrappers (`@govern_action`, `MirageGovernedTool`) defaulted to submitting tool return payloads as `ObservabilityClass.OBS_DIRECT`, risking epistemic overclaiming without an independent observer callable, and lacked a non-blocking `shadow` rollout mode.
5. Tenant GDPR DSAR exports, lead notifications, and operational status endpoints needed unified contracts.

---

## 2. Decision

1. **Fail-Closed Billing & Webhook Verification:**
   - `POST /v1/billing/webhook` verifies raw request body HMAC signatures (`Stripe-Signature` or `X-Razorpay-Signature`) fail-closed (`401 Unauthorized`) in all non-test HTTP flows.
   - Stripe checkout and settlement verification invoke the authoritative Stripe API when real keys are configured and fail closed (`503`/`402`) in `STAGING`/`PRODUCTION` if unconfigured or unpaid.
   - Razorpay test signature bypasses are restricted solely to `EnvironmentType.TEST`.
2. **Credential Hygiene & Team IAM (`POST/GET/PATCH /v1/auth/users`):**
   - Remove default SMTP credentials from `shared/config/settings.py`.
   - Add OIDC configuration settings (`OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`) and fail-closed tenant-scoped user provisioning/role management under `/v1/auth/users` (`TENANT_ADMIN` cannot mint `SUPER_ADMIN`).
3. **S3 Object Lock WORM Anchor Backend:**
   - Implement `S3ObjectLockAuditAnchorBackend` in `services/audit_anchor.py` writing compliance-locked checkpoint objects (`ObjectLockMode="COMPLIANCE"`) selectable via `AUDIT_ANCHOR_BACKEND=s3_object_lock`.
4. **SDK Epistemic Honesty & Shadow Mode Rollout:**
   - `@govern_action` (with `@governed_action` alias) and `MirageGovernedTool` require an explicit `observer` callable to emit `OBS_DIRECT`; otherwise they emit `OBS_INFERRED` transparently.
   - Add optional `enforcement_mode: Literal["enforce", "shadow"] = "enforce"` on verification and action proposals to allow non-blocking policy evaluation with full audit recording (`shadow_would_block`).
5. **Privacy DSAR & Status Contracts:**
   - Add authenticated `GET /v1/privacy/export` (compliance dossier ZIP/JSON) and `GET /v1/privacy/retention` plus redacted public `GET /v1/status`.

---

## 3. Consequences

### Positive
- Eliminates unauthenticated subscription escalation and synthetic checkout bypasses.
- Removes static secret defaults from source control and closes single-host WORM anchor risk when S3 Object Lock is configured.
- Aligns Python/JS SDKs, AutoGen/CrewAI wrappers, and Gate 5 epistemic invariants.
- Enables self-serve team RBAC, DSAR compliance exports, and safe shadow-mode onboarding.

### Negative / Operational Trade-offs
- Existing unauthenticated webhook test callers outside `ENVIRONMENT=test` must attach valid HMAC signatures.
- Enabling `s3_object_lock` requires provisioned AWS IAM permissions, S3 Object Lock-enabled bucket, and `boto3`.
- Shadow mode logs violations without blocking mutations and should only be used for controlled onboarding windows.

---

## 4. Alternatives Considered

- **Leaving `verify_stripe_payment` optimistic with manual admin reconciliation:** Rejected because any authenticated `TENANT_ADMIN` could escalate quotas and monthly budgets for free.
- **Keep `OBS_DIRECT` fallback in `@govern_action`:** Rejected because it directly violates Epistemic Outcome Independence (`AGENTS.md` §2).
