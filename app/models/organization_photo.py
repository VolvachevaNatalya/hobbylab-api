from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class OrganizationPhoto(Base):
    __tablename__ = "organization_photos"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    photo_url = Column(Text, nullable=False)

    created_at = Column(DateTime, server_default=func.now())
