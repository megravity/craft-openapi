import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from craft_wrapper.api.documents import make_router as make_documents_router
from craft_wrapper.api.errors import (
    RequestMiddleware,
    craft_error_handler,
    http_error_handler,
    validation_error_handler,
)
from craft_wrapper.api.space import make_router as make_space_router
from craft_wrapper.config import Settings, load_settings
from craft_wrapper.craft.documents.client import DocumentsClient
from craft_wrapper.craft.errors import CraftError, redact
from craft_wrapper.craft.space.client import SpaceClient
from craft_wrapper.craft.transport import CraftTransport


class SecretLogFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self.secrets)
        record.args = ()
        # Avoid unfiltered tracebacks containing an upstream URL.
        record.exc_info = None
        record.exc_text = None
        return True


def create_app(
    settings: Settings | None = None,
    *,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    documents_upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("craft_wrapper.requests").setLevel(logging.INFO)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # HTTPX normally logs the full URL at INFO, including the secret link ID.
        http_logger = logging.getLogger("httpx")
        core_logger = logging.getLogger("httpcore")
        secret_filter = SecretLogFilter(settings.secrets)
        core_level = core_logger.level
        core_logger.setLevel(logging.WARNING)
        http_logger.addFilter(secret_filter)
        core_logger.addFilter(secret_filter)
        try:
            timeout = httpx.Timeout(
                settings.craft_timeout_seconds, connect=settings.craft_connect_timeout_seconds
            )
            async with AsyncExitStack() as stack:

                async def connection(
                    url: str, transport: httpx.AsyncBaseTransport | None
                ) -> CraftTransport:
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            base_url=url.rstrip("/") + "/",
                            timeout=timeout,
                            follow_redirects=False,
                            transport=transport,
                            trust_env=False,
                        )
                    )
                    return CraftTransport(
                        client,
                        deadline_seconds=settings.craft_timeout_seconds,
                        secrets=settings.secrets,
                    )

                if settings.craft_space_base_url is not None:
                    app.state.space_client = SpaceClient(
                        await connection(
                            settings.craft_space_base_url.get_secret_value(), upstream_transport
                        )
                    )
                if settings.craft_documents_base_url is not None:
                    app.state.documents_client = DocumentsClient(
                        await connection(
                            settings.craft_documents_base_url.get_secret_value(),
                            documents_upstream_transport,
                        )
                    )
                yield
        finally:
            http_logger.removeFilter(secret_filter)
            core_logger.removeFilter(secret_filter)
            core_logger.setLevel(core_level)

    app = FastAPI(
        title="Craft HTTP tools",
        version=version("craft-openapi-wrapper"),
        lifespan=lifespan,
        description="Selected Craft Space and Multi-Document operations. Each configured "
        "adapter uses its own connection; all data routes require the wrapper bearer token. "
        "No automatic retries or fallback between connections.",
        servers=[{"url": settings.wrapper_public_url}] if settings.wrapper_public_url else [],
        redoc_url=None,
        redirect_slashes=False,
    )
    app.state.settings = settings
    app.add_middleware(RequestMiddleware)
    app.exception_handler(CraftError)(craft_error_handler)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.exception_handler(HTTPException)(http_error_handler)
    app.state.disabled_routes = []
    for router in (make_space_router(), make_documents_router()):
        app.state.disabled_routes.extend(
            route
            for route in router.routes
            if isinstance(route, APIRoute) and route.operation_id not in settings.enabled_operations
        )
        router.routes[:] = [
            route
            for route in router.routes
            if not isinstance(route, APIRoute) or route.operation_id in settings.enabled_operations
        ]
        app.include_router(router)

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    return app
