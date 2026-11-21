"""
Regression: password reset endpoints are no longer available.

POST /auth/forgot-password and POST /auth/reset-password must return 404.
These endpoints were removed when the product moved to social-only authentication.
"""
import pytest


def test_forgot_password_returns_404(client):
    resp = client.post("/auth/forgot-password", json={"email": "test@test.com"})
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


def test_reset_password_returns_404(client):
    resp = client.post(
        "/auth/reset-password",
        json={"email": "test@test.com", "otp": "123456", "new_password": "newpass123"},
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
