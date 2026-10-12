from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint


class Admin_sessions(Base):
    __tablename__ = "admin_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_admin_sessions_token_hash"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    admin_id = Column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash = Column(String(64), index=True, nullable=False)
    csrf_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_used_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
