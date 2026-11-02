"""
Regression tests for POST /upload.

All calls to storage_service.upload_file are mocked — real WebDAV is never contacted.

Coverage:
  - Authentication (anonymous, blocked user)
  - Valid uploads: JPEG, PNG (RGBA), GIF, PDF with magic bytes
  - ?type= resize preset parameter
  - Oversized files (> 10 MB)
  - Rejected file types (unknown extension, wrong MIME)
  - Content validation: corrupted image bytes, PDF without %PDF magic
  - Storage failure → 502 with no infrastructure details leaked
"""
import io
from unittest.mock import patch

import pytest

from app.core.security import create_access_token, hash_password
from app.models.user import User

_UPLOAD_URL = "/upload"
_FAKE_URL = "https://static.hobbylab.co.il/test-uuid.jpg"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="upload_user@test.com", status="active"):
    u = User(email=email, name="Test", password_hash=hash_password("pw"), status=status)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def _make_jpeg(w: int = 10, h: int = 10) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(255, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _make_png_rgba() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), color=(0, 255, 0, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _make_gif() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(0, 0, 255)).save(buf, format="GIF")
    return buf.getvalue()


def _post(client, filename, content_type, data, auth_headers=None, upload_type=None):
    params = {"type": upload_type} if upload_type else {}
    return client.post(
        _UPLOAD_URL,
        files={"file": (filename, data, content_type)},
        headers=auth_headers or {},
        params=params,
    )


# ── Authentication ────────────────────────────────────────────────────────────

def test_upload_requires_authentication(client, db):
    resp = _post(client, "test.jpg", "image/jpeg", _make_jpeg())
    assert resp.status_code == 401


def test_blocked_user_cannot_upload(client, db):
    user = _make_user(db, email="blocked_up@test.com", status="blocked")
    resp = _post(client, "test.jpg", "image/jpeg", _make_jpeg(), _auth(user.id))
    assert resp.status_code == 403


# ── Valid uploads (storage mocked) ───────────────────────────────────────────

def test_upload_valid_jpeg(client, db):
    user = _make_user(db)
    with patch("app.api.upload.storage_service.upload_file", return_value=_FAKE_URL):
        resp = _post(client, "photo.jpg", "image/jpeg", _make_jpeg(), _auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["url"] == _FAKE_URL


def test_upload_valid_png_rgba(client, db):
    user = _make_user(db, email="png_up@test.com")
    with patch("app.api.upload.storage_service.upload_file", return_value=_FAKE_URL):
        resp = _post(client, "icon.png", "image/png", _make_png_rgba(), _auth(user.id))
    assert resp.status_code == 200
    assert "url" in resp.json()


def test_upload_valid_gif(client, db):
    user = _make_user(db, email="gif_up@test.com")
    with patch("app.api.upload.storage_service.upload_file", return_value=_FAKE_URL):
        resp = _post(client, "anim.gif", "image/gif", _make_gif(), _auth(user.id))
    assert resp.status_code == 200


def test_upload_valid_pdf(client, db):
    """A minimal PDF starting with the %PDF magic bytes must be accepted."""
    user = _make_user(db, email="pdf_up@test.com")
    pdf_bytes = b"%PDF-1.4\n%%EOF"
    with patch("app.api.upload.storage_service.upload_file", return_value=_FAKE_URL):
        resp = _post(client, "doc.pdf", "application/pdf", pdf_bytes, _auth(user.id))
    assert resp.status_code == 200


def test_upload_returns_url_from_storage(client, db):
    user = _make_user(db, email="url_up@test.com")
    custom_url = "https://static.hobbylab.co.il/specific-name.jpg"
    with patch("app.api.upload.storage_service.upload_file", return_value=custom_url):
        resp = _post(client, "img.jpg", "image/jpeg", _make_jpeg(), _auth(user.id))
    assert resp.json()["url"] == custom_url


def test_upload_type_param_accepted(client, db):
    """The ?type= resize preset must not break a valid upload request."""
    user = _make_user(db, email="type_up@test.com")
    with patch("app.api.upload.storage_service.upload_file", return_value=_FAKE_URL):
        resp = _post(client, "img.jpg", "image/jpeg", _make_jpeg(), _auth(user.id), upload_type="avatar")
    assert resp.status_code == 200


# ── File-type rejection ───────────────────────────────────────────────────────

def test_upload_rejects_unknown_extension(client, db):
    user = _make_user(db, email="ext_up@test.com")
    resp = _post(client, "script.exe", "application/octet-stream", b"MZ\x90\x00", _auth(user.id))
    assert resp.status_code == 400


def test_upload_rejects_text_file(client, db):
    user = _make_user(db, email="txt_up@test.com")
    resp = _post(client, "notes.txt", "text/plain", b"hello world", _auth(user.id))
    assert resp.status_code == 400


# ── Size limit ────────────────────────────────────────────────────────────────

def test_upload_rejects_oversized_file(client, db):
    user = _make_user(db, email="big_up@test.com")
    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = _post(client, "big.jpg", "image/jpeg", big, _auth(user.id))
    assert resp.status_code == 400


# ── Content validation ────────────────────────────────────────────────────────

def test_upload_rejects_non_image_content_with_image_extension(client, db):
    """A file claiming to be JPEG but containing random bytes must return 400, not 500."""
    user = _make_user(db, email="fake_jpg@test.com")
    fake_jpeg = b"This is not a JPEG\x00" * 20
    resp = _post(client, "fake.jpg", "image/jpeg", fake_jpeg, _auth(user.id))
    assert resp.status_code == 400


def test_upload_rejects_pdf_without_magic_bytes(client, db):
    """A file with application/pdf Content-Type but no %%PDF magic must return 400."""
    user = _make_user(db, email="fake_pdf@test.com")
    fake_pdf = b"This is definitely not a PDF file"
    resp = _post(client, "fake.pdf", "application/pdf", fake_pdf, _auth(user.id))
    assert resp.status_code == 400


# ── Storage failure handling ──────────────────────────────────────────────────

def test_upload_storage_failure_returns_502(client, db):
    """A WebDAV failure must return 502 with no infrastructure details in the response."""
    user = _make_user(db, email="storeerr_up@test.com")
    internal_msg = "Connection to https://user:secret@static.hobbylab.co.il failed: timed out"
    with patch(
        "app.api.upload.storage_service.upload_file",
        side_effect=Exception(internal_msg),
    ):
        resp = _post(client, "img.jpg", "image/jpeg", _make_jpeg(), _auth(user.id))
    assert resp.status_code == 502
    body = resp.text
    assert "secret" not in body
    assert "static.hobbylab.co.il" not in body
    assert "timed out" not in body
