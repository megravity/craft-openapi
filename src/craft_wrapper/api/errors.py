import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Match

from craft_wrapper.api.schemas import ErrorDetail, ErrorInfo, ErrorResponse
from craft_wrapper.craft.errors import CraftError, redact

logger = logging.getLogger("craft_wrapper.requests")
MAX_REQUEST_BYTES = 1024 * 1024


def error_response(status: int, request_id: str, code: str, message: str, **kwargs) -> JSONResponse:
    headers = kwargs.pop("headers", None)
    payload = ErrorResponse(
        error=ErrorInfo(code=code, message=message, requestId=request_id, **kwargs)
    )
    return JSONResponse(
        status_code=status, content=payload.model_dump(exclude_none=True), headers=headers
    )


async def craft_error_handler(request: Request, error: CraftError) -> JSONResponse:
    request.state.upstream_status = error.upstream_status
    return error_response(
        error.status,
        request.state.request_id,
        error.code,
        error.message,
        upstreamStatus=error.upstream_status,
        upstreamCode=error.upstream_code,
        retryAfterSeconds=error.retry_after_seconds,
        outcomeUnknown=True if error.outcome_unknown else None,
        headers={"Retry-After": str(error.retry_after_seconds)}
        if error.retry_after_seconds is not None
        else None,
    )


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    secrets = request.app.state.settings.secrets
    # Never include Pydantic's input or context (which can contain supplied secrets).
    details = [
        ErrorDetail(
            field=redact(".".join(map(str, entry["loc"])), secrets),
            message=redact(entry["msg"], secrets),
        )
        for entry in error.errors()[:20]
    ]
    return error_response(
        422,
        request.state.request_id,
        "validation_error",
        "Invalid request parameters or body.",
        details=details,
    )


async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
    # A disabled POST may share its URL with an enabled GET. Still return 404 for
    # that disabled operation instead of the router's default 405.
    if error.status_code == 405 and any(
        route.matches(request.scope)[0] == Match.FULL for route in request.app.state.disabled_routes
    ):
        return error_response(
            404, request.state.request_id, "not_found", "Wrapper route not found."
        )
    messages = {
        401: ("unauthorized", "Wrapper bearer token required."),
        404: ("not_found", "Wrapper route not found."),
        405: ("method_not_allowed", "Method not allowed."),
        400: ("invalid_request", "Could not parse the request."),
    }
    code, message = messages.get(error.status_code, ("http_error", "Request failed."))
    return error_response(
        error.status_code, request.state.request_id, code, message, headers=error.headers
    )


class RequestMiddleware:
    """Bound incoming bodies before parsing; log only fixed operational fields."""

    def __init__(self, app, max_request_bytes: int = MAX_REQUEST_BYTES):
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        state["request_id"] = str(uuid4())
        start = perf_counter()
        status = 500
        started = False

        async def capture(message):
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", state["request_id"].encode())
                ]
            await send(message)

        async def fail(status_code, code, message):
            await error_response(status_code, state["request_id"], code, message)(
                scope, receive, capture
            )

        try:
            # Also count actual streamed bytes; Content-Length alone is not trustworthy.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.max_request_bytes:
                    await fail(413, "request_too_large", "Request body exceeds 1 MiB.")
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, replay, capture)
        except Exception:
            # Avoid traceback/exception strings: they can embed request data or a secret URL.
            if not started:
                await fail(500, "internal_error", "An internal wrapper error occurred.")
            else:
                raise RuntimeError("Wrapper response failed after headers were sent") from None
        finally:
            route = scope.get("route")
            operation_id = getattr(route, "operation_id", None) or "infrastructure_or_unmatched"
            logger.info(
                "requestId=%s operationId=%s durationMs=%.1f status=%s upstreamStatus=%s",
                state["request_id"],
                operation_id,
                (perf_counter() - start) * 1000,
                status,
                state.get("upstream_status"),
            )
