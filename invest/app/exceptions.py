"""Application-level exceptions."""


class InvestError(Exception):
    """Base class for domain errors shown to the user."""


class ValidationError(InvestError):
    """Invalid input or business rule violation."""
