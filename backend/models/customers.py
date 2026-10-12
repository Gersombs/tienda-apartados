from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint


class Customers(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("email", name="uq_customers_email"),
        Index("ix_customers_email", "email"),
        CheckConstraint("reservation_count >= 0", name="ck_customers_reservation_count_nonnegative"),
        CheckConstraint("delivered_count >= 0", name="ck_customers_delivered_count_nonnegative"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    full_name = Column(String, nullable=False)
    whatsapp = Column(String, nullable=False)
    email = Column(String, nullable=False)
    reservation_count = Column(Integer, nullable=False, default=0)
    delivered_count = Column(Integer, nullable=False, default=0)
    internal_notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
