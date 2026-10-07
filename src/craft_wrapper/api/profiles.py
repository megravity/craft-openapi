from datetime import datetime

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.routing import Match

from craft_wrapper.api.auth import check_access, require_token
from craft_wrapper.api.errors import error_response
from craft_wrapper.profiles import WriteTargets


class Capabilities(BaseModel):
    profileId: str
    adapters: list[str]
    operations: list[str]
    writeTargets: dict[str, WriteTargets]
    expiresAt: datetime | None = None


class ProfileGuard:
    """Preserve absent routes while returning authenticated denials for profile exclusions."""

    def __init__(self, app, profile_id: str, denied_routes: list[APIRoute]):
        self.app = app
        self.profile_id = profile_id
        self.denied_routes = denied_routes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope)
            request.state.profile_id = self.profile_id
            profile = request.app.state.settings.profiles[self.profile_id]
            path = scope["path"].removeprefix(scope.get("root_path", ""))
            error = None
            if profile.expired and path in {"/openapi.json", "/docs", "/docs/oauth2-redirect"}:
                error = HTTPException(403, "profile_expired")
            elif any(route.matches(scope)[0] == Match.FULL for route in self.denied_routes):
                parts = request.headers.get("authorization", "").split()
                token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None
                try:
                    check_access(request, token)
                    error = HTTPException(403, "permission_denied")
                except HTTPException as exc:
                    error = exc
            if error is not None:
                code = "unauthorized" if error.status_code == 401 else str(error.detail)
                message = {
                    "unauthorized": "Wrapper bearer token required.",
                    "permission_denied": "This profile does not permit this operation or target.",
                    "profile_expired": "This profile has expired.",
                }[code]
                await error_response(
                    error.status_code,
                    request.state.request_id,
                    code,
                    message,
                    headers=error.headers,
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def add_capabilities(app: FastAPI, profile_id: str) -> None:
    @app.get(
        "/capabilities",
        response_model=Capabilities,
        include_in_schema=False,
        dependencies=[Depends(require_token)],
    )
    async def capabilities():
        settings = app.state.settings
        profile = settings.profiles[profile_id]
        operations = settings.profile_operations(profile_id)
        targets = {}
        for adapter, configured in profile.writeTargets.items():
            document_ids = (
                configured.documentIds
                if any(
                    f"craft_{adapter}_{suffix}" in operations
                    for suffix in (
                        "insert_markdown",
                        "update_block_markdown",
                        "delete_block",
                        "add_task",
                        "update_task",
                        "delete_task",
                    )
                )
                else []
            )
            collection_ids = (
                configured.collectionIds
                if any(
                    f"craft_{adapter}_{suffix}" in operations
                    for suffix in (
                        "add_collection_item",
                        "update_collection_item_properties",
                        "delete_collection_item",
                    )
                )
                else []
            )
            if document_ids or collection_ids:
                targets[adapter] = WriteTargets(
                    documentIds=document_ids, collectionIds=collection_ids
                )
        return Capabilities(
            profileId=profile_id,
            adapters=profile.adapters,
            operations=sorted(operations),
            writeTargets=targets,
            expiresAt=profile.expiresAt,
        )
