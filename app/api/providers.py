"""
Provider management endpoints: list, link, and unlink social sign-in methods.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_recent_auth
from app.db.dependencies import get_db
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider

router = APIRouter()


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("/me/auth-providers/")
def list_auth_providers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    providers = (
        db.query(UserAuthProvider)
        .filter(UserAuthProvider.user_id == current_user.id)
        .all()
    )
    return [
        {"id": p.id, "provider": p.provider, "provider_email": p.provider_email}
        for p in providers
    ]


# ── Link helpers ───────────────────────────────────────────────────────────────

def _link_provider(
    db: Session,
    user: User,
    provider: str,
    provider_user_id: str,
    provider_email: Optional[str],
) -> UserAuthProvider:
    """Link a provider identity to `user`. Raises 409 on conflict."""
    # Check if this provider identity is already claimed by another account
    existing = (
        db.query(UserAuthProvider)
        .filter(
            UserAuthProvider.provider == provider,
            UserAuthProvider.provider_user_id == provider_user_id,
        )
        .first()
    )
    if existing:
        if existing.user_id != user.id:
            raise HTTPException(
                status_code=409,
                detail="This provider account is already linked to another user",
            )
        return existing  # idempotent

    # Check if this user already has this provider linked
    already = (
        db.query(UserAuthProvider)
        .filter(
            UserAuthProvider.user_id == user.id,
            UserAuthProvider.provider == provider,
        )
        .first()
    )
    if already:
        raise HTTPException(status_code=409, detail="Provider already linked")

    try:
        ap = UserAuthProvider(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )
        db.add(ap)
        db.commit()
        return ap
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Provider already linked")


# ── Link Google ────────────────────────────────────────────────────────────────

class LinkGoogleRequest(BaseModel):
    id_token: str


@router.post("/me/auth-providers/google")
def link_google_provider(
    payload: LinkGoogleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _recent: None = Depends(require_recent_auth),
):
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    client_ids = [
        cid.strip()
        for cid in os.getenv("GOOGLE_CLIENT_ID", "").split(",")
        if cid.strip()
    ]
    if not client_ids:
        raise HTTPException(status_code=500, detail="Google login not configured on server")

    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.id_token, google_requests.Request(), client_ids
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if id_info.get("email_verified") is not True:
        raise HTTPException(status_code=400, detail="Google account email is not verified")

    google_sub = id_info.get("sub", "")
    provider_email = id_info.get("email", "") or None

    _link_provider(db, current_user, "google", google_sub, provider_email)
    return {"status": "linked", "provider": "google"}


# ── Link Facebook ──────────────────────────────────────────────────────────────

class LinkFacebookRequest(BaseModel):
    access_token: str


@router.post("/me/auth-providers/facebook")
def link_facebook_provider(
    payload: LinkFacebookRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _recent: None = Depends(require_recent_auth),
):
    from app.api.auth import _validate_facebook_token

    data = _validate_facebook_token(payload.access_token)
    facebook_id = data.get("id", "")
    provider_email = data.get("email") or None

    _link_provider(db, current_user, "facebook", facebook_id, provider_email)
    return {"status": "linked", "provider": "facebook"}


# ── Link Apple ─────────────────────────────────────────────────────────────────

class LinkAppleRequest(BaseModel):
    id_token: str
    nonce: str  # raw nonce; backend verifies sha256(nonce) == token.nonce


@router.post("/me/auth-providers/apple")
def link_apple_provider(
    payload: LinkAppleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _recent: None = Depends(require_recent_auth),
):
    from app.api.auth import _validate_apple_token

    claims = _validate_apple_token(payload.id_token, nonce=payload.nonce)
    apple_sub = claims.get("sub", "")
    if not apple_sub:
        raise HTTPException(status_code=400, detail="Apple token missing sub claim")

    email = claims.get("email", "")
    ev = claims.get("email_verified")
    if ev is not True and ev != "true":
        email = ""

    _link_provider(db, current_user, "apple", apple_sub, email or None)
    return {"status": "linked", "provider": "apple"}


# ── Unlink ─────────────────────────────────────────────────────────────────────

@router.delete("/me/auth-providers/{provider_id}")
def unlink_auth_provider(
    provider_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _recent: None = Depends(require_recent_auth),
):
    # Lock ALL provider rows for this user in one statement to serialize concurrent unlinks.
    #
    # Race condition WITHOUT this: two concurrent DELETE requests (for provider A and B)
    # each lock their own row, both see total=2, both proceed, both delete — leaving 0 providers.
    #
    # With SELECT...FOR UPDATE on all rows: request 1 acquires all locks, counts, deletes,
    # commits; request 2 then acquires locks, sees total=1, returns 400.
    #
    # NOTE: with_for_update() is a no-op on SQLite (the test database).  This locking
    # guarantee is only enforced at runtime against PostgreSQL.
    all_providers = (
        db.query(UserAuthProvider)
        .filter(UserAuthProvider.user_id == current_user.id)
        .with_for_update()
        .all()
    )
    # Ownership check first — always 404 if the provider doesn't belong to this user.
    to_delete = next((p for p in all_providers if p.id == provider_id), None)
    if to_delete is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    if len(all_providers) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last sign-in method")

    db.delete(to_delete)
    # Bump token_version to invalidate all existing sessions
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()

    return {"status": "unlinked"}
