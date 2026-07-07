from pydantic import BaseModel


class CityResponse(BaseModel):
    id: int
    name_he: str
    name_en: str
    name_ru: str

    class Config:
        from_attributes = True
