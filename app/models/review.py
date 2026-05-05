from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, String, CheckConstraint
from sqlalchemy.sql import func
from app.db.database import Base


class Review(Base):
    __tablename__ = "reviews"

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="check_rating_range"),
    )

    id = Column(Integer, primary_key=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False
    )

    rating = Column(Integer, nullable=False)

    comment = Column(Text)

    created_at = Column(DateTime, server_default=func.now())

    status = Column(String(50), server_default="active")