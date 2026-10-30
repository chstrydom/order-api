class OrderConflictError(Exception):
    """Raised when an order reference is reused with a different payload."""


class UnknownProductError(Exception):
    """Raised when an order references a product that does not exist."""


class InvalidOrderError(Exception):
    """Raised when an order breaks a business rule (empty, or a line too large)."""
