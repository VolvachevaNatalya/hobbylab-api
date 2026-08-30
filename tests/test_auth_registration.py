import pytest

from app.api.auth import _reg_attempts

_VALID = {
    "email": "newuser@example.com",
    "name": "New User",
    "password": "securepass123",
}

# IP used as a consistent "foreign" client via X-Forwarded-For
_IP_A = "203.0.113.10"
_IP_B = "203.0.113.20"


@pytest.fixture(autouse=True)
def clear_rate_limit():
    """Reset in-process rate-limit state between tests."""
    _reg_attempts.clear()
    yield
    _reg_attempts.clear()


# ── successful registration ───────────────────────────────────────────────────

def test_register_success(client):
    resp = client.post("/auth/register", json=_VALID)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == _VALID["email"]
    assert data["name"] == _VALID["name"]
    assert "password" not in data
    assert "password_hash" not in data


# ── duplicate email ───────────────────────────────────────────────────────────

def test_register_duplicate_email_rejected(client):
    client.post("/auth/register", json=_VALID)
    resp = client.post("/auth/register", json=_VALID)
    assert resp.status_code == 400
    # Response must not expose password or internal field names
    body = resp.text.lower()
    assert "password" not in body
    assert "hash" not in body


# ── input validation ──────────────────────────────────────────────────────────

def test_register_name_empty_rejected(client):
    resp = client.post("/auth/register", json={**_VALID, "name": ""})
    assert resp.status_code == 422


def test_register_name_too_long_rejected(client):
    resp = client.post("/auth/register", json={**_VALID, "name": "A" * 101})
    assert resp.status_code == 422


def test_register_name_at_max_length_accepted(client):
    resp = client.post("/auth/register", json={**_VALID, "name": "A" * 100})
    assert resp.status_code == 200


def test_register_email_too_long_rejected(client):
    long_email = "a" * 245 + "@example.com"  # 257 chars > 254 limit
    resp = client.post("/auth/register", json={**_VALID, "email": long_email})
    assert resp.status_code == 422


def test_register_password_too_short_rejected(client):
    resp = client.post("/auth/register", json={**_VALID, "password": "12345"})
    assert resp.status_code == 422


def test_register_password_at_min_length_accepted(client):
    resp = client.post("/auth/register", json={**_VALID, "password": "123456"})
    assert resp.status_code == 200


def test_register_password_too_long_rejected(client):
    resp = client.post("/auth/register", json={**_VALID, "password": "x" * 129})
    assert resp.status_code == 422


def test_register_password_at_max_length_accepted(client):
    resp = client.post("/auth/register", json={**_VALID, "password": "x" * 128})
    assert resp.status_code == 200


# ── rate limiting ─────────────────────────────────────────────────────────────

def test_rate_limit_third_attempt_succeeds(client):
    for i in range(3):
        resp = client.post(
            "/auth/register",
            json={**_VALID, "email": f"user{i}@example.com"},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 200, f"attempt {i + 1} should succeed"


def test_rate_limit_fourth_attempt_blocked(client):
    for i in range(3):
        client.post(
            "/auth/register",
            json={**_VALID, "email": f"block{i}@example.com"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/register",
        json={**_VALID, "email": "block4@example.com"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_rate_limit_is_per_ip(client):
    """Exhausting IP_A's limit must not block IP_B."""
    for i in range(3):
        client.post(
            "/auth/register",
            json={**_VALID, "email": f"ipa{i}@example.com"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/register",
        json={**_VALID, "email": "ipb@example.com"},
        headers={"X-Real-IP": _IP_B},
    )
    assert resp.status_code == 200


def test_rate_limit_duplicate_attempts_count(client):
    """Duplicate-email attempts consume rate-limit slots."""
    # Slot 1: new account created
    client.post("/auth/register", json=_VALID, headers={"X-Real-IP": _IP_A})
    # Slots 2 & 3: duplicate → 400, but counter still advances
    for _ in range(2):
        resp = client.post("/auth/register", json=_VALID,
                           headers={"X-Real-IP": _IP_A})
        assert resp.status_code == 400
    # Slot 4: limit reached → 429
    resp = client.post(
        "/auth/register",
        json={**_VALID, "email": "fresh@example.com"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_rate_limit_validation_errors_do_not_count(client):
    """Pydantic 422 rejections are caught before the route function runs and
    therefore do not consume rate-limit slots."""
    bad = {**_VALID, "password": "x"}  # too short → 422
    for _ in range(10):
        resp = client.post("/auth/register", json=bad,
                           headers={"X-Real-IP": _IP_A})
        assert resp.status_code == 422
    # Rate limit should be intact — a valid request must still succeed
    resp = client.post("/auth/register", json=_VALID,
                       headers={"X-Real-IP": _IP_A})
    assert resp.status_code == 200


# ── logging ───────────────────────────────────────────────────────────────────

def test_successful_registration_logged(client, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="app.api.auth"):
        client.post("/auth/register", json=_VALID,
                    headers={"X-Real-IP": _IP_A,
                             "User-Agent": "TestAgent/1.0"})
    assert any("registration success" in r.message for r in caplog.records)
    assert any(_IP_A in r.message for r in caplog.records)
    assert any("password" not in r.message for r in caplog.records)


def test_duplicate_registration_logged_as_warning(client, caplog):
    import logging
    client.post("/auth/register", json=_VALID)
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        client.post("/auth/register", json=_VALID,
                    headers={"X-Real-IP": _IP_A})
    assert any("registration duplicate" in r.message for r in caplog.records)


# ── IP source preference ──────────────────────────────────────────────────────

def test_x_real_ip_is_used_for_rate_limiting(client):
    """Rate limit keyed on X-Real-IP: exhausting one IP must not block another."""
    for i in range(3):
        client.post(
            "/auth/register",
            json={**_VALID, "email": f"rip{i}@example.com"},
            headers={"X-Real-IP": _IP_A},
        )
    # IP_A is now at limit; IP_B must be unaffected
    resp = client.post(
        "/auth/register",
        json={**_VALID, "email": "ripb@example.com"},
        headers={"X-Real-IP": _IP_B},
    )
    assert resp.status_code == 200


def test_fallback_to_request_client_host_when_no_x_real_ip(client, caplog):
    """When X-Real-IP is absent the request.client.host value is used.
    TestClient sets request.client.host to 'testclient', so all no-header
    requests share that bucket — the 4th must be rate-limited."""
    import logging
    _reg_attempts.clear()
    for i in range(3):
        client.post("/auth/register", json={**_VALID, "email": f"fb{i}@example.com"})
    resp = client.post("/auth/register", json={**_VALID, "email": "fb4@example.com"})
    assert resp.status_code == 429
