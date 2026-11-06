import os

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    raise ValueError("JWT_SECRET environment variable must be set")

ALGORITHM = "HS256"


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        # Refresh tokens must never be accepted here.
        # Tokens without a "type" claim (issued before this change) are still
        # treated as access tokens for backward compatibility.
        if payload.get("type") == "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")
    # Verify token version: tokens issued before a password change carry an
    # older "tv" value and must be rejected immediately, without waiting for
    # their natural expiry.  Tokens without a "tv" claim (issued before this
    # check was added) default to 0 and remain valid as long as the user has
    # never changed their password (token_version is also 0).
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Invalid token")

    return user


def decode_refresh_token(token: str, db: Session) -> User:
    """Validate a refresh token and return the associated user.

    Raises HTTPException(401) for any failure — expired, wrong type, bad
    signature, or missing/deleted user. Error details are kept generic to
    avoid leaking information.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Invalid token")

    return user


def require_system_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_system_admin:
        raise HTTPException(status_code=403, detail="System admin access required")
    return current_user