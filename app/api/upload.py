from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.core.auth import get_current_user
from app.models.user import User
from app.services import storage_service

router = APIRouter(tags=["upload"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: jpg, png, gif, webp")

    content_type = file.content_type or ""
    if content_type and content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB")

    url = storage_service.upload_file(file_bytes, file.filename or f"upload.{ext}", content_type)
    return {"url": url}
