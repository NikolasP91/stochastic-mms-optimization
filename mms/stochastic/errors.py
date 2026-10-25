"""Structured failures for callers and command-line diagnostics."""


class OptimizationError(RuntimeError):
    """A solve could not supply a validated optimum."""

    def __init__(self, message, *, status, solver=None, details=None):
        super().__init__(message)
        self.status = status
        self.solver = solver
        self.details = details or {}

    def as_dict(self):
        return {"status": self.status, "solver": self.solver,
                "message": str(self), "details": self.details}


class InfeasibleModelError(OptimizationError):
    """Proven infeasibility, distinguishable from time limits or solver failures."""
