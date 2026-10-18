"""Typed SDK exceptions (M02).

The SDK never silently executes a sensitive operation: every failure mode
maps to a distinct exception type so callers can handle each case explicitly.
"""


class AgentTrustError(Exception):
    """Base class for all AgentTrust SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "agenttrust_error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class ConfigurationError(AgentTrustError):
    """Bad SDK setup: missing API key, misuse outside a run context, etc."""


class AuthorizationDenied(AgentTrustError):
    """The policy denied the action. Nothing was executed.

    Attributes: reason_code, tool_call_id, decision_id — safe to log.
    """

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        tool_call_id: str | None = None,
        decision_id: str | None = None,
    ) -> None:
        super().__init__(message, error_code="authorization_denied", status_code=409)
        self.reason_code = reason_code
        self.tool_call_id = tool_call_id
        self.decision_id = decision_id


class ApprovalRequired(AgentTrustError):
    """The policy routed the action to human review. Nothing was executed.

    The action stays pending until a reviewer approves it (Phase 5); the SDK
    does not block waiting for approval. Carries the approval_id so callers
    can poll with wait_for_approval().
    """

    def __init__(
        self,
        message: str,
        *,
        tool_call_id: str | None = None,
        decision_id: str | None = None,
        approval_id: str | None = None,
    ) -> None:
        super().__init__(message, error_code="approval_required", status_code=409)
        self.tool_call_id = tool_call_id
        self.decision_id = decision_id
        self.approval_id = approval_id


class ApprovalRejected(AgentTrustError):
    """A reviewer rejected the pending approval. Nothing was executed."""

    def __init__(self, message: str, *, approval_id: str | None = None) -> None:
        super().__init__(message, error_code="approval_rejected", status_code=409)
        self.approval_id = approval_id


class ApprovalExpired(AgentTrustError):
    """The pending approval expired before a reviewer decided it."""

    def __init__(self, message: str, *, approval_id: str | None = None) -> None:
        super().__init__(message, error_code="approval_expired", status_code=410)
        self.approval_id = approval_id


class ApprovalTimeout(AgentTrustError):
    """wait_for_approval() gave up waiting before the reviewer decided."""

    def __init__(self, message: str, *, approval_id: str | None = None) -> None:
        super().__init__(message, error_code="approval_timeout", status_code=408)
        self.approval_id = approval_id


class PolicyServiceUnavailable(AgentTrustError):
    """The policy service could not be reached or failed. Nothing was executed.

    Fail-closed: the SDK never executes a protected tool when authorization
    cannot be obtained.
    """
