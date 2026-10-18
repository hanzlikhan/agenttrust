"""AgentTrust Python SDK: pre-execution authorization for tool-using agents."""

from .client import AgentTrust
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

__version__ = "0.1.0"

__all__ = [
    "AgentTrust",
    "AgentTrustError",
    "ApprovalExpired",
    "ApprovalRejected",
    "ApprovalRequired",
    "ApprovalTimeout",
    "AuthorizationDenied",
    "ConfigurationError",
    "PolicyServiceUnavailable",
    "__version__",
]
