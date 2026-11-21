import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import decode_refresh_token, get_current_user
from app.db.dependencies import get_db
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider
from app.schemas.user import UserResponse
from app.core.security import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

router = APIRouter()

# Rate limiter shared by all social login endpoints (Google, Facebook, Apple).
_LOGIN_RATE_LIMIT = 10
_LOGIN_RATE_WINDOW = timedelta(minutes=15)

_login_attempts: Dict[str, List[datetime]] = defaultdict(list)
_login_lock = threading.Lock()

# Separate, more lenient rate limiter for POST /auth/refresh.
# Multiple users behind the same NAT legitimately refresh at the same time
# when their 60-minute tokens expire simultaneously.
_REFRESH_RATE_LIMIT = 30
_REFRESH_RATE_WINDOW = timedelta(minutes=15)

_refresh_attempts: Dict[str, List[datetime]] = defaultdict(list)
_refresh_lock = threading.Lock()

# Apple JWKS cache: keyed by kid, 1-hour TTL.
_jwks_cache: Dict[str, dict] = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600.0
_jwks_lock = threading.Lock()

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_CLIENT_ID = "il.co.hobbylab.app"


def _get_client_ip(request: Request) -> str:
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_login_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _LOGIN_RATE_WINDOW
    with _login_lock:
        recent = [t for t in _login_attempts[ip] if t > cutoff]
        if len(recent) >= _LOGIN_RATE_LIMIT:
            oldest = min(recent)
            retry_after = max(1, int((oldest + _LOGIN_RATE_WINDOW - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _login_attempts[ip] = recent


def _check_refresh_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _REFRESH_RATE_WINDOW
    with _refresh_lock:
        recent = [t for t in _refresh_attempts[ip] if t > cutoff]
        if len(recent) >= _REFRESH_RATE_LIMIT:
            oldest = min(recent)
            retry_after = max(1, int((oldest + _REFRESH_RATE_WINDOW - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many refresh attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _refresh_attempts[ip] = recent


# ── Apple JWKS cache ───────────────────────────────────────────────────────────

def _get_apple_jwks() -> Dict[str, dict]:
    """Fetch Apple JWKS and cache by kid with a 1-hour TTL."""
    import httpx
    global _jwks_fetched_at

    with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
            return dict(_jwks_cache)

    try:
        resp = httpx.get(APPLE_JWKS_URL, timeout=10)
    except httpx.RequestError as e:
        logger.warning("apple_jwks_unreachable | error=%s", e)
        with _jwks_lock:
            if _jwks_cache:
                return dict(_jwks_cache)
        raise HTTPException(status_code=502, detail="Could not reach Apple authentication service")

    if resp.status_code != 200:
        with _jwks_lock:
            if _jwks_cache:
                return dict(_jwks_cache)
        raise HTTPException(status_code=502, detail="Failed to fetch Apple public keys")

    new_keys = {k["kid"]: k for k in resp.json().get("keys", [])}

    with _jwks_lock:
        _jwks_cache.clear()
        _jwks_cache.update(new_keys)
        _jwks_fetched_at = time.monotonic()

    return new_keys


def _get_apple_public_key(kid: str) -> dict:
    """Return the Apple JWK for the given kid; refresh cache once on unknown kid."""
    global _jwks_fetched_at
    keys = _get_apple_jwks()
    if kid in keys:
        return keys[kid]
    with _jwks_lock:
        _jwks_fetched_at = 0.0
    keys = _get_apple_jwks()
    if kid not in keys:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return keys[kid]


# ── Token validation helpers ───────────────────────────────────────────────────

def _validate_facebook_token(access_token: str, ip: str = "unknown") -> dict:
    """Validate a Facebook access token using debug_token then /me.

    Verifies is_valid and app_id match before accepting the token.
    """
    import httpx

    app_id = os.getenv("FACEBOOK_APP_ID", "")
    app_secret = os.getenv("FACEBOOK_APP_SECRET", "")

    if not app_id or not app_secret:
        raise HTTPException(status_code=500, detail="Facebook login not configured on server")

    try:
        debug_resp = httpx.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": access_token, "access_token": f"{app_id}|{app_secret}"},
            timeout=10,
        )
    except httpx.RequestError as e:
        logger.warning("facebook_debug_token_unreachable | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=502, detail="Could not reach Facebook API")

    if debug_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    debug_data = debug_resp.json().get("data", {})
    if not debug_data.get("is_valid"):
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")
    if str(debug_data.get("app_id", "")) != str(app_id):
        logger.warning("facebook_token_wrong_app | ip=%s | token_app_id=%s", ip, debug_data.get("app_id"))
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    expires_at = int(debug_data.get("expires_at", 0))
    if expires_at > 0 and expires_at < int(time.time()):
        logger.warning("facebook_token_expired | ip=%s | expires_at=%s", ip, expires_at)
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    token_user_id = str(debug_data.get("user_id", ""))

    try:
        me_resp = httpx.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,name,email", "access_token": access_token},
            timeout=10,
        )
    except httpx.RequestError as e:
        logger.warning("facebook_api_unreachable | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=502, detail="Could not reach Facebook API")

    if me_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    me_data = me_resp.json()
    if "error" in me_data:
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    if token_user_id and str(me_data.get("id", "")) != token_user_id:
        logger.warning("facebook_token_id_mismatch | ip=%s", ip)
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    return me_data


def _validate_apple_token(id_token: str, ip: str = "unknown", nonce: str = "") -> dict:
    """Validate an Apple identity token and return its claims.

    nonce is the raw random nonce generated by the client.  The backend verifies
    sha256(nonce) == claims["nonce"], binding the token to this specific request
    and preventing replay of a stolen Apple ID token.  A nonce is always required.
    """
    import hashlib
    from jose import jwt as jose_jwt, JWTError

    try:
        header = jose_jwt.get_unverified_header(id_token)
    except JWTError as e:
        logger.warning("apple_token_invalid_header | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    public_key = _get_apple_public_key(kid)

    try:
        claims = jose_jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=APPLE_CLIENT_ID,
            issuer=APPLE_ISSUER,
        )
    except JWTError as e:
        logger.warning("apple_token_validation_failed | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Nonce validation is mandatory: the client always generates a secure random nonce,
    # passes its sha256 hash to Apple, and sends the raw nonce here.  Apple embeds the
    # hash in the token's "nonce" claim.  We verify the round-trip to prevent replay.
    if not nonce:
        raise HTTPException(status_code=400, detail="Apple nonce is required")
    token_nonce = claims.get("nonce")
    if not token_nonce:
        raise HTTPException(status_code=400, detail="Apple token missing nonce claim")
    expected = hashlib.sha256(nonce.encode()).hexdigest()
    if token_nonce != expected:
        raise HTTPException(status_code=400, detail="Apple nonce mismatch")

    return claims


# ── Provider-based account lookup / creation ───────────────────────────────────

def _get_or_create_user_by_provider(
    db: Session,
    provider: str,
    provider_user_id: str,
    provider_email: str,
    name: str,
) -> User:
    """Look up a user by provider identity (never email alone).

    1. Primary lookup by (provider, provider_user_id) in user_auth_providers.
    2. Migration compat: if no row found, check by email for pre-migration users
       with no UserAuthProvider row yet.
    3. New user: create User + UserAuthProvider atomically with IntegrityError retry.
    """
    # 1. Canonical lookup
    auth_prov = (
        db.query(UserAuthProvider)
        .filter(
            UserAuthProvider.provider == provider,
            UserAuthProvider.provider_user_id == provider_user_id,
        )
        .with_for_update()
        .first()
    )
    if auth_prov:
        # Update provider_email if the provider reports a changed address.
        # The users.email field is NOT changed — it is the account's stable identifier.
        if provider_email and auth_prov.provider_email != provider_email:
            auth_prov.provider_email = provider_email
            db.commit()
        return auth_prov.user

    # 2. Migration path: existing user without a UserAuthProvider row yet
    email_for_new_user = provider_email
    if provider_email:
        existing = db.query(User).filter(User.email == provider_email).first()
        if existing:
            if existing.password_hash is not None:
                raise HTTPException(status_code=403, detail="Account registered with a different provider")
            # Only backfill if the user has no other provider already linked.
            # If another provider is linked, they're a different person — create a new account.
            other_prov = (
                db.query(UserAuthProvider)
                .filter(
                    UserAuthProvider.user_id == existing.id,
                    UserAuthProvider.provider != provider,
                )
                .first()
            )
            if other_prov is None:
                try:
                    ap = UserAuthProvider(
                        user_id=existing.id,
                        provider=provider,
                        provider_user_id=provider_user_id,
                        provider_email=provider_email,
                    )
                    db.add(ap)
                    db.commit()
                    return existing
                except IntegrityError:
                    db.rollback()
                    auth_prov = (
                        db.query(UserAuthProvider)
                        .filter(
                            UserAuthProvider.provider == provider,
                            UserAuthProvider.provider_user_id == provider_user_id,
                        )
                        .first()
                    )
                    if auth_prov:
                        return auth_prov.user
                    return existing
            else:
                # Different person owns this email — fall through to new account with fallback email
                email_for_new_user = ""

    # 3. Brand new user
    email = email_for_new_user if email_for_new_user else f"{provider}_{provider_user_id}@noemail.local"
    try:
        user = User(email=email, name=name or email.split("@")[0], password_hash=None)
        db.add(user)
        db.flush()
        ap = UserAuthProvider(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email if provider_email else None,
        )
        db.add(ap)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        auth_prov = (
            db.query(UserAuthProvider)
            .filter(
                UserAuthProvider.provider == provider,
                UserAuthProvider.provider_user_id == provider_user_id,
            )
            .first()
        )
        if auth_prov:
            return auth_prov.user
        raise HTTPException(status_code=500, detail="Account creation conflict. Please try again.")

    return user


# ── Request models ─────────────────────────────────────────────────────────────

class GoogleLoginRequest(BaseModel):
    id_token: str


class FacebookLoginRequest(BaseModel):
    access_token: str


class AppleLoginRequest(BaseModel):
    id_token: str
    nonce: str  # raw nonce from client; backend verifies sha256(nonce) == token.nonce


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/auth/refresh")
def refresh_tokens(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access token and rotated refresh token."""
    _check_refresh_rate_limit(_get_client_ip(request))
    user = decode_refresh_token(payload.refresh_token, db)
    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/google-login")
def google_login(request: Request, payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    client_ids = [cid.strip() for cid in os.getenv("GOOGLE_CLIENT_ID", "").split(",") if cid.strip()]
    if not client_ids:
        raise HTTPException(status_code=500, detail="Google login not configured on server")

    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            client_ids,
        )
    except ValueError as e:
        logger.warning("google_token_validation_failed | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if id_info.get("email_verified") is not True:
        raise HTTPException(status_code=400, detail="Google account email is not verified")

    email: str = id_info.get("email", "")
    name: str = id_info.get("name") or email.split("@")[0]
    google_sub: str = id_info.get("sub", "")

    if not email:
        raise HTTPException(status_code=400, detail="Google token did not include an email address")

    user = _get_or_create_user_by_provider(db, "google", google_sub, email, name)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/facebook-login")
def facebook_login(request: Request, payload: FacebookLoginRequest, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    data = _validate_facebook_token(payload.access_token, ip)

    email: str = data.get("email", "")
    name: str = data.get("name") or ""
    facebook_id: str = data.get("id", "")

    user = _get_or_create_user_by_provider(db, "facebook", facebook_id, email, name)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/apple-login")
def apple_login(request: Request, payload: AppleLoginRequest, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    claims = _validate_apple_token(payload.id_token, ip, nonce=payload.nonce)

    apple_sub: str = claims.get("sub", "")
    if not apple_sub:
        raise HTTPException(status_code=400, detail="Apple token missing sub claim")

    email: str = claims.get("email", "")
    # email_verified may be a bool or the string "true"/"false".
    # Absent claim is treated as unverified (do not default to True).
    email_verified = claims.get("email_verified")
    if email_verified is not True and email_verified != "true":
        email = ""

    name: str = email.split("@")[0] if email else f"apple_{apple_sub[:8]}"

    user = _get_or_create_user_by_provider(db, "apple", apple_sub, email, name)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }
