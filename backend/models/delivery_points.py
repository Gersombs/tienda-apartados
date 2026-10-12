from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String


class Delivery_points(Base):
    __tablename__ = "delivery_points"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_delivery_points_sort_order_nonnegative"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    reference = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
