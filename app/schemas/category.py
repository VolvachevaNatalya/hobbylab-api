from pydantic import BaseModel, model_validator
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


class AdminCategoryUpdate(CategoryUpdate):
    @model_validator(mode='after')
    def name_not_null(self):
        if self.name is None and "name" in self.model_fields_set:
            raise ValueError("name cannot be null")
        return self