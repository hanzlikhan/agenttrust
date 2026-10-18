"""AgentTrust SDK client (M02). Synchronous only.

Usage:
    from agenttrust import AgentTrust

    trust = AgentTrust(api_key="...", base_url="http://localhost:8000")

    @trust.protect(tool="refund_payment")
    def refund_payment(order_id: str, amount_minor: int, currency: str = "USD"):
        # NOTE: this body is never called by the SDK. The real side effect
        # happens server-side in the trusted gateway after authorization.
        raise NotImplementedError

    with trust.run(agent="refund-support-agent", version="0.1.0") as run_id:
        result = refund_payment(order_id="ORD-100", amount_minor=4000)

Security contract:
- DENY  -> raises AuthorizationDenied; the execute endpoint is never called.
- REVIEW -> raises ApprovalRequired; nothing executes.
- Unreachable policy service / timeout / 5xx -> raises
  PolicyServiceUnavailable; nothing executes (fail closed).
- ALLOW -> exactly one gateway execute call. A single retry is permitted only
  after a network-level failure, because execute is idempotent server-side
  (single-use grant claim + one execution row per call).
"""

import functools
import inspect
import json
import time
import uuid
from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar

import httpx

from .errors import (
    AgentTrustError,
    ApprovalExpired,
    ApprovalRejected,
    ApprovalRequired,
    ApprovalTimeout,
    AuthorizationDenied,
    ConfigurationError,
    PolicyServiceUnavailable,
)

F = TypeVar("F", bound=Callable[..., Any])


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, compact separators, ASCII.

    Same contract as the server (ADR-017) so client and server agree on what
    "the same arguments" means.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class _RunContext:
    """Context manager that creates a server-side agent run (M03).

    Emits ``run.started`` on entry and ``run.completed`` (or ``run.failed``
    when the block raises) on exit. Telemetry is best-effort: a failure to
    record it never breaks the run itself.
    """

    def __init__(
        self,
        client: "AgentTrust",
        agent: str,
        version: str,
        environment: str,
    ) -> None:
        self._client = client
        self._agent = agent
        self._version = version
        self._environment = environment
        self.run_id: str | None = None

    def _telemetry(self, kind: str, payload: dict[str, Any]) -> None:
        if self.run_id is None:
            return
        try:
            self._client.report_event(self.run_id, kind, payload)
        except AgentTrustError:
            pass  # telemetry is best-effort; never break the run

    def __enter__(self) -> str:
        payload = self._client._post(
            "/api/v1/runs",
            {
                "agent_name": self._agent,
                "agent_version": self._version,
                "environment": self._environment,
            },
        )
        self.run_id = payload["run_id"]
        self._client._run_id = self.run_id
        self._telemetry(
            "run.started",
            {
                "agent": self._agent,
                "version": self._version,
                "environment": self._environment,
                "trace_id": payload.get("trace_id"),
            },
        )
        return self.run_id

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            self._telemetry("run.completed", {"agent": self._agent})
        else:
            self._telemetry(
                "run.failed",
                {"agent": self._agent, "error_type": exc_type.__name__},
            )
        self._client._run_id = None
        return False


class AgentTrust:
    """Entry point for protecting tool calls with pre-execution authorization."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 10.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ConfigurationError("AgentTrust requires a non-empty api_key.")
        if timeout <= 0:
            raise ConfigurationError("timeout must be positive.")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            # The SDK talks to an explicitly configured base URL; environment
            # proxy variables are ignored so auth-bearing policy traffic is
            # never silently rerouted.
            trust_env=False,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
        )
        self._run_id: str | None = None

    def run(
        self,
        agent: str,
        version: str = "0.1.0",
        environment: str = "local",
    ) -> _RunContext:
        """Open a server-side run; yields the run_id inside the block."""
        return _RunContext(self, agent, version, environment)

    def protect(self, tool: str) -> Callable[[F], F]:
        """Decorate a function so calls go through authorize -> gateway.

        The decorated function's body is never executed by the SDK; it only
        provides the signature used to bind call arguments.
        """
        if not tool or not tool.strip():
            raise ConfigurationError("protect() requires a non-empty tool name.")

        def decorator(fn: F) -> F:
            signature = inspect.signature(fn)

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if self._run_id is None:
                    raise ConfigurationError(
                        "protect()ed functions must be called inside a "
                        "trust.run(...) context."
                    )
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = dict(bound.arguments)
                # Fail fast on non-JSON arguments before any network call.
                canonical_json(arguments)
                return self._invoke(tool.strip(), arguments)

            return wrapper  # type: ignore[return-value]

        return decorator

    def report_event(
        self, run_id: str, kind: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Report a telemetry event for a run (M02/M08).

        Payloads must already be redacted — the SDK never inspects them.
        Recording is server-side and transactional; the returned body
        includes the accepted count and the assigned project_seq range.
        """
        if not run_id or not run_id.strip():
            raise ConfigurationError("report_event() requires a non-empty run_id.")
        if not kind or not kind.strip():
            raise ConfigurationError("report_event() requires a non-empty kind.")
        # Fail fast on non-JSON payloads before any network call.
        canonical_json(payload or {})
        return self._post(
            f"/api/v1/runs/{run_id.strip()}/events",
            {"events": [{"kind": kind.strip(), "payload": payload or {}}]},
        )

    def wait_for_approval(
        self,
        approval_id: str,
        timeout_s: float = 300.0,
        poll_interval_s: float = 1.0,
    ) -> Any:
        """Block until a pending approval is decided, then execute if approved.

        Polls the lightweight approval status endpoint. On APPROVED, calls
        the trusted execute endpoint once and returns the gateway result.
        Raises ApprovalRejected / ApprovalExpired when the reviewer (or the
        clock) decides against the action, and ApprovalTimeout when the
        timeout elapses first. Never executes on any other outcome.
        """
        if not approval_id or not approval_id.strip():
            raise ConfigurationError("wait_for_approval() requires a non-empty approval_id.")
        if timeout_s <= 0:
            raise ConfigurationError("timeout_s must be positive.")
        approval_id = approval_id.strip()
        deadline = time.monotonic() + timeout_s
        while True:
            status = self._get(f"/api/v1/approvals/{approval_id}/status")
            state = status.get("state")
            if state == "APPROVED":
                return self._execute(status["tool_call_id"], None)
            if state == "REJECTED":
                raise ApprovalRejected(
                    "The pending approval was rejected by the reviewer.",
                    approval_id=approval_id,
                )
            if state == "EXPIRED":
                raise ApprovalExpired(
                    "The pending approval expired before a reviewer decided it.",
                    approval_id=approval_id,
                )
            if time.monotonic() >= deadline:
                raise ApprovalTimeout(
                    f"Timed out after {timeout_s}s waiting for approval {approval_id}.",
                    approval_id=approval_id,
                )
            time.sleep(min(poll_interval_s, max(0.0, deadline - time.monotonic())))

    # -- internals ---------------------------------------------------------

    def _get(self, path: str) -> dict[str, Any]:
        """GET JSON and return the parsed body, mapping failures to typed errors."""
        headers = {"X-Correlation-ID": uuid.uuid4().hex}
        try:
            response = self._http.get(path, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PolicyServiceUnavailable(
                f"Policy service unreachable at {self._base_url}{path}: {exc}"
            ) from exc
        if response.status_code >= 500:
            raise PolicyServiceUnavailable(
                f"Policy service error ({response.status_code}); failing closed.",
                status_code=response.status_code,
            )
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except ValueError:
            pass
        if response.status_code in (401, 403):
            raise ConfigurationError(
                f"API authentication failed ({response.status_code}): check the API key.",
            )
        if response.status_code >= 400:
            raise AgentTrustError(
                body.get("message", f"Request failed ({response.status_code})."),
                error_code=body.get("error_code", "request_failed"),
                status_code=response.status_code,
            )
        return body

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON and return the parsed body, mapping failures to typed errors."""
        headers = {"X-Correlation-ID": uuid.uuid4().hex}
        try:
            response = self._http.post(path, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PolicyServiceUnavailable(
                f"Policy service unreachable at {self._base_url}{path}: {exc}"
            ) from exc
        if response.status_code >= 500:
            raise PolicyServiceUnavailable(
                f"Policy service error ({response.status_code}); failing closed.",
                status_code=response.status_code,
            )
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except ValueError:
            pass
        if response.status_code in (401, 403):
            raise ConfigurationError(
                f"API authentication failed ({response.status_code}): check the API key.",
            )
        if response.status_code >= 400:
            raise AgentTrustError(
                body.get("message", f"Request failed ({response.status_code})."),
                error_code=body.get("error_code", "request_failed"),
                status_code=response.status_code,
            )
        return body

    def _invoke(self, tool: str, arguments: dict[str, Any]) -> Any:
        idempotency_key = uuid.uuid4().hex
        authz = self._post(
            "/api/v1/tool-calls/authorize",
            {
                "run_id": self._run_id,
                "tool_name": tool,
                "arguments": arguments,
                "idempotency_key": idempotency_key,
            },
        )
        outcome = authz.get("outcome")
        tool_call_id = authz.get("tool_call_id")
        decision_id = authz.get("decision_id")
        if outcome == "DENY":
            # The execute endpoint is deliberately never called here.
            raise AuthorizationDenied(
                authz.get("explanation", "The policy denied this action."),
                reason_code=authz.get("reason_code", "DENIED"),
                tool_call_id=tool_call_id,
                decision_id=decision_id,
            )
        if outcome == "REVIEW":
            raise ApprovalRequired(
                authz.get("explanation", "This action requires human approval."),
                tool_call_id=tool_call_id,
                decision_id=decision_id,
                approval_id=authz.get("approval_id"),
            )
        if outcome != "ALLOW":
            raise AgentTrustError(
                f"Unexpected authorize outcome: {outcome!r}. Failing closed."
            )
        return self._execute(tool_call_id, arguments)

    def _execute(self, tool_call_id: str, arguments: dict[str, Any] | None) -> Any:
        path = f"/api/v1/tool-calls/{tool_call_id}/execute"
        # When arguments are None the gateway executes against the stored
        # grant (used by wait_for_approval after the review step).
        payload = {} if arguments is None else {"arguments": arguments}
        try:
            result = self._post(path, payload)
        except PolicyServiceUnavailable:
            # Exactly one retry: execute is idempotent server-side (the grant
            # claim and the single execution row live in one transaction), so
            # a retry after a network failure cannot cause a second effect.
            # Retries never apply to DENY/REVIEW — those paths never call
            # execute at all.
            result = self._post(path, payload)
        except AgentTrustError as exc:
            if exc.error_code == "approval_required":
                raise ApprovalRequired(str(exc)) from exc
            raise AuthorizationDenied(
                str(exc),
                reason_code=exc.error_code,
            ) from exc
        return result.get("result")
