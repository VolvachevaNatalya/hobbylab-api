"""
Regression: email/password authentication endpoints are no longer available.

POST /auth/register, POST /auth/login, POST /auth/change-password,
POST /auth/forgot-password, and POST /auth/reset-password must all return 404.
"""
import pytest
import os


class TestEmailPasswordEndpointsRemoved:
    def test_register_returns_404(self, client):
        resp = client.post(
            "/auth/register",
            json={"email": "test@test.com", "name": "Test", "password": "test123"},
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_login_returns_404(self, client):
        resp = client.post(
            "/auth/login",
            data={"username": "test@test.com", "password": "test"},
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_change_password_returns_404(self, client):
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "old", "new_password": "new123"},
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_forgot_password_returns_404(self, client):
        resp = client.post(
            "/auth/forgot-password",
            json={"email": "test@test.com"},
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_reset_password_returns_404(self, client):
        resp = client.post(
            "/auth/reset-password",
            json={"email": "test@test.com", "otp": "123456", "new_password": "newpass"},
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


class TestEmailPasswordAccountCannotBypassSocialAuth:
    """
    Regression: an account that has a password_hash must not be allowed to
    authenticate via any social provider, even if the email matches.
    """

    def test_email_password_account_blocked_at_google_login(self, client, db):
        from unittest.mock import patch
        from app.core.security import hash_password
        from app.models.user import User

        u = User(
            email="ep_google@test.com",
            name="EP",
            password_hash=hash_password("secret"),
            status="active",
        )
        db.add(u)
        db.commit()

        id_info = {"email": "ep_google@test.com", "name": "EP User", "sub": "g123", "email_verified": True}
        with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
             patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
            resp = client.post("/auth/google-login", json={"id_token": "fake-token"})

        assert resp.status_code == 403, (
            f"email/password account must not authenticate via Google (got {resp.status_code})"
        )

    def test_email_password_account_blocked_at_facebook_login(self, client, db):
        from unittest.mock import patch
        from app.core.security import hash_password
        from app.models.user import User

        u = User(
            email="ep_facebook@test.com",
            name="EP",
            password_hash=hash_password("secret"),
            status="active",
        )
        db.add(u)
        db.commit()

        fb_debug = {"data": {"is_valid": True, "app_id": "fake-app-id", "user_id": "fb123"}}
        fb_me = {"id": "fb123", "name": "EP User", "email": "ep_facebook@test.com"}

        with patch.dict(os.environ, {"FACEBOOK_APP_ID": "fake-app-id", "FACEBOOK_APP_SECRET": "fake-secret"}), \
             patch("app.api.auth._validate_facebook_token", return_value=fb_me):
            resp = client.post("/auth/facebook-login", json={"access_token": "fake-token"})

        assert resp.status_code == 403, (
            f"email/password account must not authenticate via Facebook (got {resp.status_code})"
        )

    def test_email_password_account_blocked_at_apple_login(self, client, db):
        from unittest.mock import patch
        from app.core.security import hash_password
        from app.models.user import User

        u = User(
            email="ep_apple@test.com",
            name="EP",
            password_hash=hash_password("secret"),
            status="active",
        )
        db.add(u)
        db.commit()

        apple_claims = {"sub": "apple_sub_123", "email": "ep_apple@test.com", "email_verified": True}

        with patch("app.api.auth._validate_apple_token", return_value=apple_claims):
            resp = client.post("/auth/apple-login", json={"id_token": "fake-token", "nonce": "dummy-nonce"})

        assert resp.status_code == 403, (
            f"email/password account must not authenticate via Apple (got {resp.status_code})"
        )


class TestCrossProviderAccountIsolation:
    """
    Regression: a Google account must not be accessible via Facebook (or vice versa)
    even when both present the same email address.
    """

    def test_google_and_facebook_same_email_are_separate_accounts(self, client, db):
        from unittest.mock import patch
        from app.models.user import User
        from app.models.user_auth_provider import UserAuthProvider

        # Create a Google user
        google_id_info = {
            "email": "shared@example.com",
            "name": "Google User",
            "sub": "google_sub_xyz",
            "email_verified": True,
        }
        with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
             patch("google.oauth2.id_token.verify_oauth2_token", return_value=google_id_info):
            resp = client.post("/auth/google-login", json={"id_token": "fake"})
        assert resp.status_code == 200
        google_access_token = resp.json()["access_token"]

        # Now log in via Facebook claiming the same email — must create a separate account
        fb_me = {"id": "fb_xyz", "name": "Facebook User", "email": "shared@example.com"}
        with patch("app.api.auth._validate_facebook_token", return_value=fb_me):
            resp2 = client.post("/auth/facebook-login", json={"access_token": "fake-fb"})
        assert resp2.status_code == 200
        fb_access_token = resp2.json()["access_token"]

        # The two tokens must reference different accounts
        assert google_access_token != fb_access_token
        # Verify two separate UserAuthProvider rows exist
        google_prov = db.query(UserAuthProvider).filter_by(provider="google", provider_user_id="google_sub_xyz").first()
        fb_prov = db.query(UserAuthProvider).filter_by(provider="facebook", provider_user_id="fb_xyz").first()
        assert google_prov is not None
        assert fb_prov is not None
        assert google_prov.user_id != fb_prov.user_id
