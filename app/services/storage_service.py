import os
import uuid
from webdav3.client import Client

_PUBLIC_BASE = "https://static.hobbylab.co.il"

_WEBDAV_URL = os.getenv("WEBDAV_URL", "davs://static.hobbylab.co.il/upload")
_WEBDAV_USERNAME = os.getenv("WEBDAV_USERNAME", "")
_WEBDAV_PASSWORD = os.getenv("WEBDAV_PASSWORD", "")

# webdavclient3 expects an https/http URL, not davs://
_webdav_host = _WEBDAV_URL.replace("davs://", "https://").replace("dav://", "http://")


def _get_client() -> Client:
    return Client({
        "webdav_hostname": _webdav_host,
        "webdav_login": _WEBDAV_USERNAME,
        "webdav_password": _WEBDAV_PASSWORD,
    })


def upload_file(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload file bytes to WebDAV and return the public URL."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    unique_name = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())

    client = _get_client()
    # write to a temp buffer that webdavclient3 can consume
    import io
    client.upload_to(buff=io.BytesIO(file_bytes), remote_path=unique_name)

    return f"{_PUBLIC_BASE}/{unique_name}"


def delete_file(file_url: str) -> None:
    """Delete a file from WebDAV given its public URL."""
    if not file_url.startswith(_PUBLIC_BASE + "/"):
        return
    filename = file_url[len(_PUBLIC_BASE) + 1:]
    client = _get_client()
    client.clean(filename)
