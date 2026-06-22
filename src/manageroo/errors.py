class MANAGEROOError(Exception):
    """Base error."""


class ConfigurationError(MANAGEROOError):
    """Configuration is invalid or incomplete."""


class SafetyError(MANAGEROOError):
    """A safety invariant was violated."""


class StateTransitionError(MANAGEROOError):
    """An invalid state transition was attempted."""


class ContextBudgetError(MANAGEROOError):
    """Required context cannot fit within the configured budget."""


class AgentExecutionError(MANAGEROOError):
    """An external coding agent failed or returned invalid output."""


class ValidationError(MANAGEROOError):
    """An artifact or agent response failed validation."""


class BlockingDecisionError(MANAGEROOError):
    """A product decision must be made before implementation can proceed."""


class GateFailure(MANAGEROOError):
    """A deterministic verification gate failed."""
