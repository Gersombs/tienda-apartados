from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint


class Products(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_products_slug"),
        Index("ix_products_slug", "slug"),
        CheckConstraint("price >= 0", name="ck_products_price_nonnegative"),
        CheckConstraint("sort_order >= 0", name="ck_products_sort_order_nonnegative"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    short_description = Column(String, nullable=True)
    full_description = Column(String, nullable=True)
    ingredients = Column(String, nullable=True)
    usage_instructions = Column(String, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), index=True, nullable=True)
    price = Column(Float, nullable=False)
    tags = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_featured = Column(Boolean, nullable=False, default=False)
    is_archived = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
