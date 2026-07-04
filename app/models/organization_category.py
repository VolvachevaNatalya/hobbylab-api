from sqlalchemy import Column, Integer, ForeignKey
from app.db.database import Base


class OrganizationCategory(Base):
    __tablename__ = "organization_categories"

    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    category_id = Column(
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    position = Column(Integer, nullable=False, default=0)
