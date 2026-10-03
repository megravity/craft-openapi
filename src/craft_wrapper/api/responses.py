from typing import Any

from craft_wrapper.api.schemas import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Craft rejected the request.",
        401: "Missing or invalid wrapper bearer token.",
        404: "Craft resource not found.",
        409: "Craft conflict.",
        413: "Request body exceeds 1 MiB.",
        422: "Invalid request parameters or body.",
        429: "Craft rate limit; inspect Retry-After.",
        500: "Internal wrapper error.",
        502: "Craft access, response, or upstream failure.",
        503: "Could not reach Craft.",
        504: "Craft request timed out.",
    }.items()
}
