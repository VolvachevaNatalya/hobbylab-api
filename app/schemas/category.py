from pydantic import BaseModel
from typing import Optional


class CategoryCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    name_ru: Optional[str] = None
    name_he: Optional[str] = None
    icon_url: Optional[str] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    name_en: Optional[str] = None
    name_ru: Optional[str] = None
    name_he: Optional[str] = None
    icon_url: Optional[str] = None

    class Config:
        from_attributes = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    name_ru: Optional[str] = None
    name_he: Optional[str] = None
    icon_url: Optional[str] = None