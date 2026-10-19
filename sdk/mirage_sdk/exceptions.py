"""MIRAGE SDK Exceptions.

Hierarchy:
    MirageError
    ├── MirageAuthenticationError (HTTP 401)
    ├── MirageAuthorizationError (HTTP 403)
    ├── MirageNotFoundError (HTTP 404)
    ├── MirageValidationError (HTTP 400 / 422)
    ├── MirageRateLimitError (HTTP 429)
    ├── MirageServerError (HTTP 5xx)
    ├── MirageTransportError (Connection / Network)
    └── MirageExecutionUncertainError (Execution state uncertain, crash / timeout)
"""

from typing import Any


class MirageError(Exception):
    """Base exception for all MIRAGE SDK operations.

    Credentials and authentication headers are strictly sanitized and never
    included in error messages or string representations.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.request_id = request_id

    def __repr__(self) -> str:
        parts = [f"message={self.message!r}"]
        if self.status_code is not None:
            parts.append(f"status_code={self.status_code}")
        if self.request_id is not None:
            parts.append(f"request_id={self.request_id!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class MirageAuthenticationError(MirageError):
    """Raised when authentication fails (HTTP 401: missing, malformed, or invalid API key)."""


class MirageAuthorizationError(MirageError):
    """Raised when an action or route is forbidden (HTTP 403: insufficient scopes, role restrictions, or tenant mismatch)."""


class MirageNotFoundError(MirageError):
    """Raised when the requested resource (action, output, server) is not found (HTTP 404)."""


class MirageValidationError(MirageError):
    """Raised when request payload fails schema or parameter validation (HTTP 400 or 422)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 422,
        response_body: Any = None,
        request_id: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body, request_id=request_id)
        self.errors: list[dict[str, Any]] = errors or []


class MirageRateLimitError(MirageError):
    """Raised when rate limit or quota is exceeded (HTTP 429)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 429,
        response_body: Any = None,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body, request_id=request_id)
        self.retry_after = retry_after


class MirageExecutionUncertainError(MirageError):
    """Raised when a mutating action's execution state cannot be definitively confirmed.

    CRITICAL INVARIANT:
        When a mutating action times out, encounters a network disconnect during execution,
        or is returned with state='EXECUTION_UNCERTAIN', the remote side-effect MAY have
        already completed or partially completed on external targets.

        The client MUST NEVER automatically redispatch or retry the mutating request blindly.
        Callers must either:
        1. Query action status via `client.get_action(action_id)`
        2. Perform independent Gate 5 outcome verification via `client.get_outcome(action_id)`
        3. Use `client.reconcile_action(...)` for stranded action recovery.
    """

    def __init__(
        self,
        message: str,
        *,
        action_id: str | None = None,
        state: str = "EXECUTION_UNCERTAIN",
        status_code: int | None = None,
        response_body: Any = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body, request_id=request_id)
        self.action_id = action_id
        self.state = state

    def __repr__(self) -> str:
        parts = [f"message={self.message!r}", f"action_id={self.action_id!r}", f"state={self.state!r}"]
        return f"{self.__class__.__name__}({', '.join(parts)})"


class MirageServerError(MirageError):
    """Raised when the server encounters an unhandled internal error (HTTP 5xx)."""


class MirageTransportError(MirageError):
    """Raised on connection error, DNS failure, or protocol failure before reaching the server."""
