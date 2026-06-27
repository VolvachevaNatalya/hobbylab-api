from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class OrganizationInviteCode(Base):
    __tablename__ = "organization_invite_codes"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    code = Column(String(50), unique=True, nullable=False, index=True)
    default_role = Column(String(50), nullable=False, server_default="member")
    requires_approval = Column(Boolean, nullable=False, server_default="true", default=True)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    expires_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())
