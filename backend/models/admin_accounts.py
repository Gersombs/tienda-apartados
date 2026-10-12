from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint


class Admin_accounts(Base):
    __tablename__ = "admin_accounts"
    __table_args__ = (
        UniqueConstraint("auth_user_id", name="uq_admin_accounts_auth_user_id"),
        UniqueConstraint("normalized_email", name="uq_admin_accounts_normalized_email"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    auth_user_id = Column(String(64), index=True, nullable=False)
    email = Column(String(320), nullable=False)
    normalized_email = Column(String(320), nullable=False)
    password_hash = Column(String(512), nullable=False)
    name = Column(String, nullable=True)
    role = Column(String(32), nullable=False, default="owner")
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
