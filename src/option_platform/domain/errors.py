class DomainError(ValueError):
    """Base error for invalid domain operations."""


class InvalidTransition(DomainError):
    """Raised when an order transition violates the state machine."""


class DuplicateEvent(DomainError):
    """Raised when an event cannot safely be applied twice."""


class StaleMarketData(DomainError):
    """Raised when market data is too old for trading."""
