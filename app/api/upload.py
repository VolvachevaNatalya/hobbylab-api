from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.core.auth import get_current_user
from app.models.user import User
from app.services import storage_service

router = APIRouter(tags=["upload"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
_EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}
_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = file.content_type or ""

    ext_ok = ext in _ALLOWED_EXTENSIONS
    content_type_ok = content_type in _ALLOWED_TYPES

    if not ext_ok and not content_type_ok:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: jpg, png, gif, webp")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB")

    # Derive a valid MIME type from the extension when the client sends
    # None or application/octet-stream (common with Flutter's MultipartFile.fromPath).
    effective_content_type = content_type if content_type_ok else _EXT_TO_MIME.get(ext, "application/octet-stream")

    url = storage_service.upload_file(file_bytes, filename or f"upload.{ext}", effective_content_type)
    return {"url": url}
