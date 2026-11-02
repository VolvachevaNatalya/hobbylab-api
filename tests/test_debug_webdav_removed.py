"""
Regression tests: WebDAV diagnostic endpoints must not exist.

GET /debug-webdav was removed: public endpoint that exposed WebDAV credentials.
POST /admin/test-webdav was removed: leaked WebDAV username in the response body,
made real external network requests, and wrote test files to production storage.
"""


def test_debug_webdav_is_gone(client):
    response = client.get("/debug-webdav")
    assert response.status_code == 404, (
        "GET /debug-webdav must not exist — it was a public endpoint that "
        "probed production WebDAV credentials without authentication"
    )


def test_admin_test_webdav_is_gone(client):
    response = client.post("/admin/test-webdav")
    assert response.status_code in (404, 401, 403), (
        "POST /admin/test-webdav must not exist — it leaked WebDAV credentials "
        "in responses and made real external network requests to production storage"
    )
