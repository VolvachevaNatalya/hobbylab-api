"""
CORS middleware tests.

Middleware behaviour is tested via a purpose-built mini FastAPI app so that
importing app.main (which runs DB migrations on load) is avoided.

The parse_cors_origins() helper is tested separately for env-var parsing
logic; that function lives in app.core.config, which has no side-effects.
"""
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import parse_cors_origins


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cors_client(origins: list) -> TestClient:
    """Minimal FastAPI app wired with CORSMiddleware for isolated testing."""
    mini = FastAPI()
    mini.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @mini.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(mini, raise_server_exceptions=False)


ALLOWED = "https://admin.hobbylab.co.il"
BLOCKED  = "https://evil.example.com"


# ── No-Origin requests ────────────────────────────────────────────────────────

def test_no_origin_header_gets_no_cors_headers():
    """Requests without an Origin header are not cross-origin; no CORS header emitted."""
    resp = _cors_client(["*"]).get("/ping")
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


# ── Wildcard origin ───────────────────────────────────────────────────────────

def test_wildcard_returns_cors_header_for_any_origin():
    """allow_origins=["*"] grants any Origin the CORS wildcard header."""
    resp = _cors_client(["*"]).get("/ping", headers={"Origin": ALLOWED})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_wildcard_preflight_returns_cors_headers():
    """Preflight OPTIONS from any origin is answered with CORS headers under wildcard."""
    resp = _cors_client(["*"]).options(
        "/ping",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"


# ── Specific allowlist ────────────────────────────────────────────────────────

def test_allowed_origin_gets_cors_header():
    """A request from an explicitly listed origin receives the CORS header."""
    resp = _cors_client([ALLOWED]).get("/ping", headers={"Origin": ALLOWED})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED


def test_disallowed_origin_gets_no_cors_header():
    """A request from an unlisted origin does not receive a CORS header."""
    resp = _cors_client([ALLOWED]).get("/ping", headers={"Origin": BLOCKED})
    assert "access-control-allow-origin" not in resp.headers


def test_allowed_origin_preflight_succeeds():
    """Preflight from an allowed origin receives the correct CORS allow headers."""
    resp = _cors_client([ALLOWED]).options(
        "/ping",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED


def test_disallowed_origin_preflight_gets_no_cors_header():
    """Preflight from an unlisted origin is not granted CORS access."""
    resp = _cors_client([ALLOWED]).options(
        "/ping",
        headers={
            "Origin": BLOCKED,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


# ── parse_cors_origins env-var parsing ───────────────────────────────────────

def test_parse_cors_origins_default_is_wildcard(monkeypatch):
    """Missing CORS_ORIGINS defaults to ['*'] — preserves current production behaviour."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert parse_cors_origins() == ["*"]


def test_parse_cors_origins_explicit_wildcard(monkeypatch):
    """CORS_ORIGINS=* is normalised to ['*']."""
    monkeypatch.setenv("CORS_ORIGINS", "*")
    assert parse_cors_origins() == ["*"]


def test_parse_cors_origins_single_url(monkeypatch):
    """A single URL is returned as a one-element list."""
    monkeypatch.setenv("CORS_ORIGINS", ALLOWED)
    assert parse_cors_origins() == [ALLOWED]


def test_parse_cors_origins_multiple_urls(monkeypatch):
    """Comma-separated URLs produce a list with one entry per origin."""
    monkeypatch.setenv("CORS_ORIGINS", f"{ALLOWED},{BLOCKED}")
    result = parse_cors_origins()
    assert ALLOWED in result
    assert BLOCKED in result
    assert len(result) == 2


def test_parse_cors_origins_trims_whitespace(monkeypatch):
    """Whitespace around commas is stripped."""
    monkeypatch.setenv("CORS_ORIGINS", f"  {ALLOWED} ,  {BLOCKED}  ")
    result = parse_cors_origins()
    assert ALLOWED in result
    assert BLOCKED in result
    assert all(" " not in o for o in result)
