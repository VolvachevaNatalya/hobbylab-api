import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.core.security import create_access_token
from app.models.support_request import SupportRequest
from app.models.user import User

_FAKE_ENV = {
    "TELEGRAM_BOT_TOKEN": "fake-token",
    "TELEGRAM_SUPPORT_CHAT_ID": "-999999",
}

_VALID = {"subject": "billing", "message": "Charged twice."}


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="support_user@test.com", name="Support User"):
    user = User(email=email, name=name, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user):
    token = create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {token}"}


def _post(client, user, body=None):
    """POST /support/ with Telegram mocked out."""
    with patch.dict(os.environ, _FAKE_ENV), \
         patch("app.core.telegram.requests.post") as mock_tg:
        mock_tg.return_value = MagicMock(status_code=200)
        resp = client.post("/support/", json=body or _VALID, headers=_auth(user))
    return resp, mock_tg


def _seed_records(db, user, count, age=timedelta(seconds=0)):
    """Insert `count` support_request rows directly, optionally back-dated."""
    now = datetime.now(timezone.utc) - age
    for _ in range(count):
        db.add(SupportRequest(
            user_id=user.id,
            subject="seed",
            message="seeded",
            status="new",
            created_at=now,
        ))
    db.commit()


# ── authentication ────────────────────────────────────────────────────────────

def test_unauthenticated_rejected(client):
    resp = client.post("/support/", json=_VALID)
    assert resp.status_code == 401


# ── valid request ─────────────────────────────────────────────────────────────

def test_valid_request_accepted(client, db):
    user = _make_user(db)
    resp, mock_tg = _post(client, user)

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user.id
    assert data["subject"] == "billing"
    assert data["message"] == "Charged twice."
    assert data["status"] == "new"
    assert "id" in data and "created_at" in data

    mock_tg.assert_called_once()
    sent_text = mock_tg.call_args[1]["json"]["text"]
    assert str(data["id"]) in sent_text
    assert user.name in sent_text
    assert user.email in sent_text


# ── input validation ──────────────────────────────────────────────────────────

def test_missing_fields_rejected(client, db):
    user = _make_user(db, email="u_missing@test.com")
    with patch("app.core.telegram.requests.post"):
        resp = client.post("/support/", json={}, headers=_auth(user))
    assert resp.status_code == 422


def test_whitespace_only_subject_rejected(client, db):
    user = _make_user(db, email="u_ws_subj@test.com")
    with patch("app.core.telegram.requests.post"):
        resp = client.post("/support/", json={"subject": "   ", "message": "ok"}, headers=_auth(user))
    assert resp.status_code == 422


def test_whitespace_only_message_rejected(client, db):
    user = _make_user(db, email="u_ws_msg@test.com")
    with patch("app.core.telegram.requests.post"):
        resp = client.post("/support/", json={"subject": "ok", "message": "\t\n  "}, headers=_auth(user))
    assert resp.status_code == 422


def test_oversized_subject_rejected(client, db):
    user = _make_user(db, email="u_long_subj@test.com")
    with patch("app.core.telegram.requests.post"):
        resp = client.post(
            "/support/",
            json={"subject": "x" * 151, "message": "ok"},
            headers=_auth(user),
        )
    assert resp.status_code == 422


def test_oversized_message_rejected(client, db):
    user = _make_user(db, email="u_long_msg@test.com")
    with patch("app.core.telegram.requests.post"):
        resp = client.post(
            "/support/",
            json={"subject": "ok", "message": "x" * 10001},
            headers=_auth(user),
        )
    assert resp.status_code == 422


def test_subject_trimmed(client, db):
    user = _make_user(db, email="u_trim@test.com")
    resp, _ = _post(client, user, {"subject": "  billing  ", "message": "ok"})
    assert resp.status_code == 200
    assert resp.json()["subject"] == "billing"


# ── rate limiting: 10-minute window ──────────────────────────────────────────

def test_fifth_request_within_10m_allowed(client, db):
    user = _make_user(db, email="u_10m_ok@test.com")
    _seed_records(db, user, count=4)
    resp, _ = _post(client, user)
    assert resp.status_code == 200


def test_sixth_request_within_10m_rejected(client, db):
    user = _make_user(db, email="u_10m_429@test.com")
    _seed_records(db, user, count=5)
    resp, mock_tg = _post(client, user)
    assert resp.status_code == 429
    mock_tg.assert_not_called()


def test_old_records_do_not_count_toward_10m_limit(client, db):
    user = _make_user(db, email="u_10m_old@test.com")
    # 5 records older than 10 minutes — should not trigger the window limit
    _seed_records(db, user, count=5, age=timedelta(minutes=11))
    resp, _ = _post(client, user)
    assert resp.status_code == 200


# ── rate limiting: 24-hour window ────────────────────────────────────────────

def test_twentieth_request_within_24h_allowed(client, db):
    user = _make_user(db, email="u_24h_ok@test.com")
    # Seed records outside the 10-minute window but inside the 24-hour window
    # so only the 24h limit applies.
    _seed_records(db, user, count=19, age=timedelta(minutes=11))
    resp, _ = _post(client, user)
    assert resp.status_code == 200


def test_twentyfirst_request_within_24h_rejected(client, db):
    user = _make_user(db, email="u_24h_429@test.com")
    _seed_records(db, user, count=20, age=timedelta(minutes=11))
    resp, mock_tg = _post(client, user)
    assert resp.status_code == 429
    mock_tg.assert_not_called()


# ── rate limit is per user ────────────────────────────────────────────────────

def test_rate_limit_does_not_block_other_users(client, db):
    blocked = _make_user(db, email="u_blocked@test.com")
    other = _make_user(db, email="u_other@test.com")

    _seed_records(db, blocked, count=5)  # blocked user is at limit

    # other user has no records — must not be affected
    resp, _ = _post(client, other)
    assert resp.status_code == 200


# ── rate-limited request leaves no trace ─────────────────────────────────────

def test_rate_limited_request_not_stored(client, db):
    user = _make_user(db, email="u_notstore@test.com")
    _seed_records(db, user, count=5)

    before_count = db.query(SupportRequest).filter(SupportRequest.user_id == user.id).count()
    resp, mock_tg = _post(client, user)

    assert resp.status_code == 429
    after_count = db.query(SupportRequest).filter(SupportRequest.user_id == user.id).count()
    assert after_count == before_count
    mock_tg.assert_not_called()


# ── Telegram failure ──────────────────────────────────────────────────────────

def test_telegram_failure_does_not_lose_record(client, db):
    user = _make_user(db, email="u_tg_fail@test.com")

    with patch.dict(os.environ, _FAKE_ENV), \
         patch("app.core.telegram.requests.post", side_effect=Exception("timeout")):
        resp = client.post("/support/", json=_VALID, headers=_auth(user))

    assert resp.status_code == 200
    record = db.query(SupportRequest).filter(SupportRequest.user_id == user.id).first()
    assert record is not None
    assert record.status == "new"


# ── Telegram special characters ───────────────────────────────────────────────

def test_telegram_special_characters_sent_as_plain_text(client, db):
    user = _make_user(db, email="u_tg_chars@test.com")
    nasty = {"subject": "<b>bold</b> & 'quotes'", "message": "**markdown** [link](http://evil.example)"}

    with patch.dict(os.environ, _FAKE_ENV), \
         patch("app.core.telegram.requests.post") as mock_tg:
        mock_tg.return_value = MagicMock(status_code=200)
        resp = client.post("/support/", json=nasty, headers=_auth(user))

    assert resp.status_code == 200
    sent_text = mock_tg.call_args[1]["json"]["text"]
    # Telegram call must not include parse_mode — plain text only
    sent_json = mock_tg.call_args[1]["json"]
    assert "parse_mode" not in sent_json
    # Raw characters arrive unchanged (no escaping, no stripping)
    assert "<b>bold</b>" in sent_text
    assert "**markdown**" in sent_text
