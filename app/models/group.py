from sqlalchemy import Column, Integer, String, ForeignKey
from app.db.database import Base


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)

    class_id = Column(
        Integer,
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False
    )

    name = Column(String(255))

    age_from = Column(Integer)
    age_to = Column(Integer)

    capacity = Column(Integer)

    status = Column(String(50), server_default="active")