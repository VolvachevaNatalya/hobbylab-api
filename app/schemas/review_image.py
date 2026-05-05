from pydantic import BaseModel


class ReviewImageCreate(BaseModel):
    review_id: int
    image_url: str


class ReviewImageResponse(BaseModel):
    id: int
    review_id: int
    image_url: str

    class Config:
        from_attributes = True