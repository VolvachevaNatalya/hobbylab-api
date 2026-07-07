from pydantic import BaseModel, EmailStr, field_validator
from typing import List, Optional
from decimal import Decimal
from datetime import datetime

from app.schemas.category import CategoryResponse

ALLOWED_STATUSES = {"pending", "active", "blocked"}


class OrganizationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    instagram_url: Optional[str] = None
    facebook_url: Optional[str] = None
    telegram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    tiktok_url: Optional[str] = None
    whatsapp_url: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    city_id: Optional[int] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    category_ids: List[int]

    @field_validator("category_ids")
    @classmethod
    def validate_category_ids(cls, v: List[int]) -> List[int]:
        if len(v) < 1:
            raise ValueError("At least one category is required")
        if len(v) > 10:
            raise ValueError("At most 10 categories are allowed")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate category IDs are not allowed")
        return v


class OrganizationResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    logo_url: Optional[str]
    banner_url: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    website: Optional[str]
    instagram_url: Optional[str]
    facebook_url: Optional[str]
    telegram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    tiktok_url: Optional[str] = None
    whatsapp_url: Optional[str] = None
    address: Optional[str]
    city: Optional[str]
    city_id: Optional[int] = None
    city_name_he: Optional[str] = None
    city_name_en: Optional[str] = None
    city_name_ru: Optional[str] = None
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]
    verified: bool
    status: str
    created_at: datetime
    updated_at: Optional[datetime]
    trial_lesson_available: bool = False
    trial_lesson_price: Optional[float] = None
    trial_lesson_comment: Optional[str] = None
    distance_km: Optional[float] = None
    average_rating: float = 0.0
    review_count: int = 0
    role: Optional[str] = None
    categories: List[CategoryResponse] = []

    class Config:
        from_attributes = True


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    instagram_url: Optional[str] = None
    facebook_url: Optional[str] = None
    telegram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    tiktok_url: Optional[str] = None
    whatsapp_url: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    city_id: Optional[int] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    status: Optional[str] = None
    trial_lesson_available: Optional[bool] = None
    trial_lesson_price: Optional[float] = None
    trial_lesson_comment: Optional[str] = None
    category_ids: Optional[List[int]] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}")
        return v

    @field_validator("category_ids")
    @classmethod
    def validate_category_ids(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if len(v) < 1:
            raise ValueError("At least one category is required when provided")
        if len(v) > 10:
            raise ValueError("At most 10 categories are allowed")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate category IDs are not allowed")
        return v
