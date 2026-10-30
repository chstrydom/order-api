class OrderConflictError(Exception):
    """Raised when an order reference is reused with a different payload."""


class UnknownProductError(Exception):
    """Raised when an order references a product that does not exist."""
