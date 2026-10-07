import asyncio
import json
import math
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from craft_wrapper.craft.errors import CraftError, redact
from craft_wrapper.craft.query import query_params

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass
class RequestOutcome:
    submitted: bool = False


request_outcome: ContextVar[RequestOutcome | None] = ContextVar(
    "craft_request_outcome", default=None
)


def retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isascii() and value.isdigit():
        # Bound untrusted headers before integer conversion.
        return int(value) if len(value) <= 9 else None
    try:
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            return None
        return max(0, math.ceil((target - datetime.now(UTC)).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return None


class CraftTransport:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        deadline_seconds: float = 30,
        secrets: tuple[str, ...] = (),
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ):
        self.client = client
        self.deadline_seconds = deadline_seconds
        self.secrets = secrets
        self.max_response_bytes = max_response_bytes

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | bool | int | None] | None = None,
        body: dict[str, Any] | None = None,
        markdown: bool = False,
    ) -> Any:
        write = method != "GET"
        upstream_status = None
        try:
            async with asyncio.timeout(self.deadline_seconds):
                outcome = request_outcome.get()
                if write and outcome is not None:
                    outcome.submitted = True
                async with self.client.stream(
                    method,
                    path,
                    params=query_params(params or {}),
                    json=body,
                    headers={"Accept": "text/markdown" if markdown else "application/json"},
                    follow_redirects=False,
                ) as response:
                    upstream_status = response.status_code
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunks) + len(chunk) > self.max_response_bytes:
                            raise CraftError(
                                "craft_response_too_large",
                                "Craft response exceeds 8 MiB. Use narrower filters or maxDepth.",
                                upstream_status=response.status_code,
                                outcome_unknown=write,
                            )
                        chunks.extend(chunk)
                    if not 200 <= response.status_code < 300:
                        raise self._http_error(response, bytes(chunks), write)
                    media_type = response.headers.get("content-type", "").split(";")[0].lower()
                    if markdown:
                        if media_type != "text/markdown":
                            raise ValueError("Unexpected Markdown content type")
                        return bytes(chunks).decode("utf-8")
                    if media_type != "application/json" and not media_type.endswith("+json"):
                        raise ValueError("Unexpected JSON content type")
                    return json.loads(
                        chunks, parse_constant=self._reject_constant, parse_float=self._finite_float
                    )
        except CraftError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise CraftError(
                "craft_timeout",
                "Craft request timed out.",
                504,
                upstream_status=upstream_status,
                outcome_unknown=write,
            ) from None
        except httpx.RequestError:
            raise CraftError(
                "craft_unavailable",
                "Could not reach Craft.",
                503,
                upstream_status=upstream_status,
                outcome_unknown=write,
            ) from None
        except (ValueError, UnicodeError, RecursionError):
            raise CraftError(
                "craft_upstream_error",
                "Craft returned an invalid response.",
                upstream_status=upstream_status,
                outcome_unknown=write,
            ) from None

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError("Non-JSON numeric constant")

    @staticmethod
    def _finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON number")
        return result

    def _http_error(self, response: httpx.Response, data: bytes, write: bool) -> CraftError:
        upstream_status = response.status_code
        mappings = {
            400: (400, "craft_rejected_request", "Craft rejected the request."),
            422: (400, "craft_rejected_request", "Craft rejected the request."),
            401: (
                502,
                "craft_access_error",
                "The configured Craft connection cannot access this resource.",
            ),
            403: (
                502,
                "craft_access_error",
                "The configured Craft connection cannot access this resource.",
            ),
            404: (404, "craft_not_found", "Craft resource not found."),
            409: (409, "craft_conflict", "Craft reported a conflict."),
            429: (429, "craft_rate_limited", "Craft rate limit reached. Wait before trying again."),
        }
        status, code, message = mappings.get(
            upstream_status, (502, "craft_upstream_error", "Craft returned an upstream error.")
        )
        upstream_code = None
        try:
            payload = json.loads(data)
            if isinstance(payload, dict):
                fields = payload.get("error", payload)
                if isinstance(fields, dict):
                    if isinstance(fields.get("code"), str):
                        upstream_code = redact(fields["code"], self.secrets)
                    # Redirects must not expose Location/body contents as a public message.
                    if upstream_status >= 400 and isinstance(fields.get("message"), str):
                        message = redact(fields["message"], self.secrets) or message
        except (ValueError, UnicodeError, RecursionError):
            pass
        return CraftError(
            code,
            message,
            status,
            upstream_status=upstream_status,
            upstream_code=upstream_code,
            retry_after_seconds=retry_after_seconds(response.headers.get("retry-after")),
            outcome_unknown=write,
        )
