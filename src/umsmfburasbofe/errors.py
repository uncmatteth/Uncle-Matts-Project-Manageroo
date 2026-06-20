class UMSMFBURASBOFEError(Exception):
    """Base error."""


class ConfigurationError(UMSMFBURASBOFEError):
    """Configuration is invalid or incomplete."""


class SafetyError(UMSMFBURASBOFEError):
    """A safety invariant was violated."""


class StateTransitionError(UMSMFBURASBOFEError):
    """An invalid state transition was attempted."""


class ContextBudgetError(UMSMFBURASBOFEError):
    """Required context cannot fit within the configured budget."""


class AgentExecutionError(UMSMFBURASBOFEError):
    """An external coding agent failed or returned invalid output."""


class ValidationError(UMSMFBURASBOFEError):
    """An artifact or agent response failed validation."""


class BlockingDecisionError(UMSMFBURASBOFEError):
    """A product decision must be made before implementation can proceed."""


class GateFailure(UMSMFBURASBOFEError):
    """A deterministic verification gate failed."""
