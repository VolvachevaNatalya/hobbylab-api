from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ClassCreate(BaseModel):
    organization_id: int
    category_id: int
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[float] = None
    price_type: Optional[str] = None


class ClassResponse(BaseModel):
    id: int
    organization_id: int
    category_id: int
    name: str
    description: Optional[str]
    image_url: Optional[str]
    price: Optional[float]
    price_type: Optional[str]
    status: str
    created_at: datetime
    organization_name: Optional[str] = None
    category_name: Optional[str] = None

    class Config:
        from_attributes = True

class ClassUpdate(BaseModel):
    organization_id: Optional[int] = None
    category_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[float] = None
    price_type: Optional[str] = None
    status: Optional[str] = None