"""
Regression test: GET /debug-webdav must not exist.
The endpoint was removed because it was public and exposed WebDAV credentials.
"""


def test_debug_webdav_is_gone(client):
    response = client.get("/debug-webdav")
    assert response.status_code == 404, (
        "GET /debug-webdav must not exist — it was a public endpoint that "
        "probed production WebDAV credentials without authentication"
    )
