from sqlalchemy import Column, Integer, Text, ForeignKey
from app.db.database import Base


class ReviewImage(Base):
    __tablename__ = "review_images"

    id = Column(Integer, primary_key=True)

    review_id = Column(
        Integer,
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False
    )

    image_url = Column(Text, nullable=False)