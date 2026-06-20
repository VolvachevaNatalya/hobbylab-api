from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class ReviewCreate(BaseModel):
    organization_id: int
    rating: int
    comment: Optional[str] = None
    photo_urls: Optional[List[str]] = None


class ReviewUpdate(BaseModel):
    rating: Optional[int] = None
    comment: Optional[str] = None
    status: Optional[str] = None


class ReviewResponse(BaseModel):
    id: int
    user_id: int
    organization_id: int
    rating: int
    comment: Optional[str]
    created_at: datetime
    status: str
    user_name: Optional[str] = None
    photo_urls: List[str] = []

    class Config:
        from_attributes = True