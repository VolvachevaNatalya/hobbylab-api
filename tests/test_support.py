import os
from unittest.mock import patch, MagicMock

from app.core.security import create_access_token
from app.models.support_request import SupportRequest
from app.models.user import User


def _make_user(db, email="support_user@test.com", name="Support User"):
    user = User(email=email, name=name, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_headers(user):
    token = create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {token}"}


_FAKE_ENV = {
    "TELEGRAM_BOT_TOKEN": "fake-token",
    "TELEGRAM_SUPPORT_CHAT_ID": "-999999",
}


def test_create_support_request_success(client, db):
    user = _make_user(db)

    with patch.dict(os.environ, _FAKE_ENV), \
         patch("app.core.telegram.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        resp = client.post(
            "/support/",
            json={"subject": "billing", "message": "Charged twice."},
            headers=_auth_headers(user),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user.id
    assert data["subject"] == "billing"
    assert data["message"] == "Charged twice."
    assert data["status"] == "new"
    assert "id" in data
    assert "created_at" in data

    mock_post.assert_called_once()
    sent_text = mock_post.call_args[1]["json"]["text"]
    assert str(data["id"]) in sent_text
    assert user.name in sent_text
    assert user.email in sent_text


def test_telegram_failure_does_not_lose_record(client, db):
    user = _make_user(db, email="user2@test.com")

    with patch("app.core.telegram.requests.post", side_effect=Exception("timeout")):
        resp = client.post(
            "/support/",
            json={"subject": "bug", "message": "App crashes on open."},
            headers=_auth_headers(user),
        )

    assert resp.status_code == 200
    record = db.query(SupportRequest).filter(SupportRequest.user_id == user.id).first()
    assert record is not None
    assert record.subject == "bug"
    assert record.status == "new"


def test_create_support_request_unauthenticated(client):
    resp = client.post(
        "/support/",
        json={"subject": "help", "message": "I need help."},
    )
    assert resp.status_code == 401


def test_create_support_request_missing_fields(client, db):
    user = _make_user(db, email="user3@test.com")

    with patch("app.core.telegram.requests.post"):
        resp = client.post(
            "/support/",
            json={},
            headers=_auth_headers(user),
        )

    assert resp.status_code == 422
