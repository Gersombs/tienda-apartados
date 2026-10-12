from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String


class Delivery_slots(Base):
    __tablename__ = "delivery_slots"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_delivery_slots_weekday"),
        CheckConstraint("capacity >= 0", name="ck_delivery_slots_capacity_nonnegative"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    delivery_point_id = Column(Integer, ForeignKey("delivery_points.id", ondelete="CASCADE"), index=True, nullable=False)
    weekday = Column(Integer, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
