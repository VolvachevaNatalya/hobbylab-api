from typing import Optional
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query

from app.core.auth import get_current_user
from app.models.user import User
from app.services import storage_service

router = APIRouter(tags=["upload"])

_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
_EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
}
_ALLOWED_TYPES = set(_EXT_TO_MIME.values())
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
_MAX_SIZE = 10 * 1024 * 1024  # 10 MB

# (max_width, max_height, crop_to_square)
_RESIZE_CONFIGS: dict[str, tuple[int, int, bool]] = {
    "avatar":  (400, 400, True),
    "banner":  (1200, 400, False),
    "gallery": (1200, 900, False),
    "class":   (800, 600, False),
    "event":   (800, 600, False),
}
_DEFAULT_RESIZE: tuple[int, int, bool] = (1200, 900, False)


def _has_alpha(img) -> bool:
    try:
        if img.mode == "RGBA":
            return img.getchannel("A").getextrema()[0] < 255
        if img.mode == "P":
            return "transparency" in img.info
    except Exception:
        pass
    return False


def _process_image(file_bytes: bytes, ext: str, upload_type: Optional[str]) -> tuple[bytes, str, str]:
    """Resize/convert image. Returns (bytes, content_type, file_ext)."""
    from PIL import Image

    if ext == "gif":
        return file_bytes, "image/gif", "gif"

    img = Image.open(io.BytesIO(file_bytes))
    keep_as_png = ext == "png" and _has_alpha(img)

    max_w, max_h, crop_square = _RESIZE_CONFIGS.get(upload_type, _DEFAULT_RESIZE) if upload_type else _DEFAULT_RESIZE

    if crop_square:
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        target = min(side, max_w)
        if img.size[0] > target:
            img = img.resize((target, target), Image.LANCZOS)
    else:
        img.thumbnail((max_w, max_h), Image.LANCZOS)

    buf = io.BytesIO()
    if keep_as_png:
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png", "png"

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "image/jpeg", "jpg"


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    upload_type: Optional[str] = Query(None, alias="type"),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = file.content_type or ""

    ext_ok = ext in _ALLOWED_EXTENSIONS
    content_type_ok = content_type in _ALLOWED_TYPES

    if not ext_ok and not content_type_ok:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed formats: jpeg, jpg, png, gif, webp, pdf",
        )

    # Resolve canonical MIME type and extension
    if content_type_ok:
        mime = content_type
        ext = _MIME_TO_EXT.get(mime, ext)
    else:
        mime = _EXT_TO_MIME.get(ext, "application/octet-stream")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB")

    if mime.startswith("image/"):
        file_bytes, mime, ext = _process_image(file_bytes, ext, upload_type)

    url = storage_service.upload_file(file_bytes, f"upload.{ext}", mime)
    return {"url": url}
