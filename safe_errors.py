"""Stable public error codes; exception messages and request data stay private."""

PUBLIC_ERROR_CODES = frozenset({
    "TIMEOUT", "PERMISSION_DENIED", "NOT_FOUND", "INVALID_DATA",
    "IO_ERROR", "OPERATION_FAILED",
})


def public_error(exc: BaseException) -> str:
    """Describe a failure without inspecting its text, arguments or request URL."""
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, PermissionError):
        return "PERMISSION_DENIED"
    if isinstance(exc, FileNotFoundError):
        return "NOT_FOUND"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "INVALID_DATA"
    if isinstance(exc, OSError):
        return "IO_ERROR"
    return "OPERATION_FAILED"
