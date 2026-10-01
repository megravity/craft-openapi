import re
from collections.abc import Iterable


class CraftError(Exception):
    """Transport/domain failure; contains only information safe for the public API."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 502,
        *,
        upstream_status: int | None = None,
        upstream_code: str | None = None,
        retry_after_seconds: int | None = None,
        outcome_unknown: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.upstream_status = upstream_status
        self.upstream_code = upstream_code
        self.retry_after_seconds = retry_after_seconds
        self.outcome_unknown = outcome_unknown


def redact(value: str, secrets: Iterable[str]) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(
        r"https?://(?:connect|mcp)\.craft\.do/links/[^\s\"'<>]+",
        "[REDACTED CRAFT LINK]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(Bearer|Basic)\s+[^\s\"'<>]+", r"\1 [REDACTED]", value, flags=re.IGNORECASE)
    return " ".join(value.split())[:500]
