import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False, scheme_name="WrapperBearer")


def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = request.app.state.settings.wrapper_api_token.get_secret_value().encode("utf-8")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), expected
    ):
        raise HTTPException(
            401, "Wrapper bearer token required.", headers={"WWW-Authenticate": "Bearer"}
        )
