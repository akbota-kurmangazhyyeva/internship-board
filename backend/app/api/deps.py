from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.security import decode_access_token

SessionDep = Annotated[Session, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def optional_user(
    session: SessionDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User | None:
    """Guests may browse. A token that is present but invalid is still an error, so clients notice expiry."""
    if creds is None:
        return None
    user_id = decode_access_token(creds.credentials)
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise _unauthorized("invalid or expired token")
    return user


def required_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise _unauthorized("authentication required")
    return user


OptionalUser = Annotated[User | None, Depends(optional_user)]
CurrentUser = Annotated[User, Depends(required_user)]
