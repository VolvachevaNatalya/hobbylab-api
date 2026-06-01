from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Literal
from decimal import Decimal
from datetime import datetime

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
    address: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None


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
    address: Optional[str]
    city: Optional[str]
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]
    verified: bool
    status: str
    created_at: datetime
    updated_at: Optional[datetime]
    distance_km: Optional[float] = None
    average_rating: float = 0.0
    review_count: int = 0

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
    address: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}")
        return v