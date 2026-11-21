"""Tests for GET/PUT /me/notification-preferences."""
import pytest

from app.core.security import create_access_token
from app.models.user import User

_GET_URL = "/me/notification-preferences"
_PUT_URL = "/me/notification-preferences"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="pref@x.com", **kwargs):
    u = User(
        email=email,
        name="Pref User",
        password_hash=None,
        **kwargs,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    token = create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# GET /me/notification-preferences
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetNotificationPreferences:
    def test_requires_auth(self, client):
        resp = client.get(_GET_URL)
        assert resp.status_code == 401

    def test_returns_200_for_authenticated_user(self, client, db):
        u = _make_user(db, "gp_ok@x.com")
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.status_code == 200

    def test_returns_all_four_fields(self, client, db):
        u = _make_user(db, "gp_fields@x.com")
        resp = client.get(_GET_URL, headers=_auth(u))
        data = resp.json()
        assert "notif_appointments" in data
        assert "notif_chat" in data
        assert "notif_activity" in data
        assert "notif_offers" in data

    def test_default_appointments_is_true(self, client, db):
        u = _make_user(db, "gp_def_ap@x.com")
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_appointments"] is True

    def test_default_chat_is_true(self, client, db):
        u = _make_user(db, "gp_def_ch@x.com")
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_chat"] is True

    def test_default_activity_is_false(self, client, db):
        u = _make_user(db, "gp_def_ac@x.com")
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_activity"] is False

    def test_default_offers_is_true(self, client, db):
        u = _make_user(db, "gp_def_of@x.com")
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_offers"] is True

    def test_returns_stored_values(self, client, db):
        u = _make_user(
            db, "gp_stored@x.com",
            notif_appointments=False,
            notif_chat=False,
            notif_activity=True,
            notif_offers=False,
        )
        resp = client.get(_GET_URL, headers=_auth(u))
        data = resp.json()
        assert data["notif_appointments"] is False
        assert data["notif_chat"] is False
        assert data["notif_activity"] is True
        assert data["notif_offers"] is False

    def test_user_cannot_read_other_users_preferences(self, client, db):
        u1 = _make_user(db, "gp_priv1@x.com")
        _make_user(db, "gp_priv2@x.com")
        resp = client.get(_GET_URL, headers=_auth(u1))
        # Must see u1's defaults, not u2's.
        assert resp.status_code == 200
        assert resp.json()["notif_appointments"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# PUT /me/notification-preferences
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateNotificationPreferences:
    def test_requires_auth(self, client):
        resp = client.put(_PUT_URL, json={"notif_appointments": False})
        assert resp.status_code == 401

    def test_returns_200_on_valid_update(self, client, db):
        u = _make_user(db, "up_ok@x.com")
        resp = client.put(_PUT_URL, json={"notif_appointments": False}, headers=_auth(u))
        assert resp.status_code == 200

    def test_update_appointments(self, client, db):
        u = _make_user(db, "up_ap@x.com")
        client.put(_PUT_URL, json={"notif_appointments": False}, headers=_auth(u))
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_appointments"] is False

    def test_update_chat(self, client, db):
        u = _make_user(db, "up_ch@x.com")
        client.put(_PUT_URL, json={"notif_chat": False}, headers=_auth(u))
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_chat"] is False

    def test_update_activity(self, client, db):
        u = _make_user(db, "up_ac@x.com")
        client.put(_PUT_URL, json={"notif_activity": True}, headers=_auth(u))
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_activity"] is True

    def test_update_offers(self, client, db):
        u = _make_user(db, "up_of@x.com")
        client.put(_PUT_URL, json={"notif_offers": False}, headers=_auth(u))
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_offers"] is False

    def test_partial_update_does_not_change_unmentioned_fields(self, client, db):
        u = _make_user(db, "up_part@x.com")
        client.put(_PUT_URL, json={"notif_appointments": False}, headers=_auth(u))
        resp = client.get(_GET_URL, headers=_auth(u))
        data = resp.json()
        assert data["notif_chat"] is True
        assert data["notif_activity"] is False
        assert data["notif_offers"] is True

    def test_update_all_fields_at_once(self, client, db):
        u = _make_user(db, "up_all@x.com")
        payload = {
            "notif_appointments": False,
            "notif_chat": False,
            "notif_activity": True,
            "notif_offers": False,
        }
        resp = client.put(_PUT_URL, json=payload, headers=_auth(u))
        assert resp.status_code == 200
        data = resp.json()
        assert data["notif_appointments"] is False
        assert data["notif_chat"] is False
        assert data["notif_activity"] is True
        assert data["notif_offers"] is False

    def test_response_body_reflects_new_values(self, client, db):
        u = _make_user(db, "up_body@x.com")
        resp = client.put(_PUT_URL, json={"notif_chat": False}, headers=_auth(u))
        assert resp.json()["notif_chat"] is False

    def test_preferences_persist_after_separate_get(self, client, db):
        u = _make_user(db, "up_persist@x.com")
        client.put(_PUT_URL, json={"notif_offers": False}, headers=_auth(u))
        db.expire_all()
        resp = client.get(_GET_URL, headers=_auth(u))
        assert resp.json()["notif_offers"] is False

    def test_empty_body_changes_nothing(self, client, db):
        u = _make_user(db, "up_empty@x.com")
        client.put(_PUT_URL, json={}, headers=_auth(u))
        resp = client.get(_GET_URL, headers=_auth(u))
        data = resp.json()
        assert data["notif_appointments"] is True
        assert data["notif_chat"] is True
        assert data["notif_activity"] is False
        assert data["notif_offers"] is True

    def test_invalid_body_type_returns_422(self, client, db):
        u = _make_user(db, "up_422@x.com")
        # Pydantic coerces "yes"/"no" to bool; use a string that cannot be cast.
        resp = client.put(_PUT_URL, json={"notif_appointments": "maybe"}, headers=_auth(u))
        assert resp.status_code == 422

    def test_user_cannot_affect_another_users_preferences(self, client, db):
        u1 = _make_user(db, "up_iso1@x.com")
        u2 = _make_user(db, "up_iso2@x.com")
        client.put(_PUT_URL, json={"notif_appointments": False}, headers=_auth(u1))
        resp = client.get(_GET_URL, headers=_auth(u2))
        # u2's defaults must be untouched.
        assert resp.json()["notif_appointments"] is True
