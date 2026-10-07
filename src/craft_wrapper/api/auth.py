import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False, scheme_name="WrapperBearer")


def check_access(request: Request, token: str | None) -> None:
    settings = request.app.state.settings
    profile_id = getattr(request.app.state, "profile_id", None)
    expected = settings.profile_token(profile_id) if profile_id else settings.wrapper_api_token
    if (
        token is None
        or expected is None
        or not secrets.compare_digest(
            token.encode("utf-8"), expected.get_secret_value().encode("utf-8")
        )
    ):
        raise HTTPException(
            401, "Wrapper bearer token required.", headers={"WWW-Authenticate": "Bearer"}
        )
    ensure_active(request)


def ensure_active(request: Request) -> None:
    profile_id = getattr(request.app.state, "profile_id", None)
    if profile_id:
        profile = request.app.state.settings.profiles[profile_id]
        if not profile.enabled:
            raise HTTPException(403, "permission_denied")
        if profile.expired:
            raise HTTPException(403, "profile_expired")


def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    check_access(request, credentials.credentials if credentials else None)
