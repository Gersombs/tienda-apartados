"""Public shop contracts. Persistence and administrative fields never appear here."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from core.reservation_limits import (
    MAX_RESERVATION_LINES,
    MAX_RESERVATION_TOTAL_UNITS,
    MAX_RESERVATION_UNITS_PER_LINE,
)


class PublicInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PublicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CartLine(PublicInput):
    variant_id: int = Field(gt=0)
    quantity: int = Field(default=1, gt=0, le=MAX_RESERVATION_UNITS_PER_LINE)


class AvailabilityRequest(PublicInput):
    items: list[CartLine] = Field(min_length=1, max_length=MAX_RESERVATION_LINES)


class ReservationPublicCreate(PublicInput):
    full_name: str = Field(min_length=2, max_length=160)
    whatsapp: str = Field(min_length=10, max_length=24)
    email: EmailStr
    delivery_point_id: int = Field(gt=0)
    delivery_date: str = Field(min_length=10, max_length=10)
    slot_start: str = Field(min_length=4, max_length=5)
    notes: str = Field(default="", max_length=1000)
    privacy_accepted: bool
    fingerprint: str = Field(default="", max_length=80)
    items: list[CartLine] = Field(min_length=1, max_length=MAX_RESERVATION_LINES)

    @field_validator("privacy_accepted")
    @classmethod
    def privacy_must_be_accepted(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Debes aceptar el aviso de privacidad.")
        return value

    @model_validator(mode="after")
    def cart_must_stay_within_public_limits(self) -> "ReservationPublicCreate":
        variant_ids = [line.variant_id for line in self.items]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("Cada variante debe aparecer una sola vez en el apartado.")
        if sum(line.quantity for line in self.items) > MAX_RESERVATION_TOTAL_UNITS:
            raise ValueError(
                f"El apartado no puede superar {MAX_RESERVATION_TOTAL_UNITS} unidades."
            )
        return self


class ReservationCreatedPublic(PublicOutput):
    folio: str
    private_token: str
    total_amount: float
    message: str


class ConfirmationTokenRequest(PublicInput):
    # Shape validation stays in the constant-response lookup so malformed and
    # unknown capabilities are indistinguishable to callers.
    token: str = ""


class CategoryPublic(PublicOutput):
    name: str
    slug: str
    description: str
    image_url: str


class ProductImagePublic(PublicOutput):
    url: str
    alt_text: str


class ProductVariantPublic(PublicOutput):
    id: int
    option_name: str
    option_value: str
    label: str
    price: float
    available_units: int
    availability: str


class ProductSummaryPublic(PublicOutput):
    name: str
    slug: str
    short_description: str
    price: float
    category_name: str
    category_slug: str
    is_featured: bool
    tags: list[str]
    image_url: str
    image_alt: str
    available_units: int
    availability: str


class ProductDetailPublic(ProductSummaryPublic):
    full_description: str
    ingredients: str
    usage_instructions: str
    images: list[ProductImagePublic]
    variants: list[ProductVariantPublic]


class ProductsPublicResponse(PublicOutput):
    items: list[ProductSummaryPublic]
    total: int
    category: CategoryPublic | None


class ProductDetailResponse(PublicOutput):
    product: ProductDetailPublic
    related: list[ProductSummaryPublic]


class DeliverySlotPublic(PublicOutput):
    id: int
    start_time: str
    end_time: str
    label: str
    capacity: int
    remaining: int | None


class DeliveryDayPublic(PublicOutput):
    date: str
    weekday_label: str
    slots: list[DeliverySlotPublic]


class DeliveryPointPublic(PublicOutput):
    id: int
    name: str
    kind: str
    address: str
    city: str
    reference: str
    notes: str
    days: list[DeliveryDayPublic]


class StoreSettingsPublic(PublicOutput):
    shop_name: str
    tagline: str
    logo_url: str
    hero_image_url: str
    color_bg: str
    color_text: str
    color_accent: str
    contact_email: str
    contact_whatsapp: str
    instagram_url: str
    tiktok_url: str
    facebook_url: str
    how_it_works: str
    faq_content: str
    privacy_policy: str
    reservation_policy: str
    delivery_instructions: str
    reservation_window_days: int
    grace_period_hours: int


class BootstrapPublicResponse(PublicOutput):
    settings: StoreSettingsPublic
    categories: list[CategoryPublic]
    featured: list[ProductSummaryPublic]
    delivery_points: list[DeliveryPointPublic]


class DeliveryOptionsPublicResponse(PublicOutput):
    delivery_points: list[DeliveryPointPublic]
    reservation_window_days: int
    grace_period_hours: int


class AvailabilityLinePublic(PublicOutput):
    variant_id: int
    ok: bool
    available_units: int | None = None
    unit_price: float | None = None
    product_name: str | None = None
    variant_label: str | None = None
    reason: str


class AvailabilityPublicResponse(PublicOutput):
    lines: list[AvailabilityLinePublic]
    all_ok: bool


class ConfirmationItemPublic(PublicOutput):
    product_name: str
    variant_label: str
    unit_price: float
    quantity: int
    line_total: float
    image_url: str


class ConfirmationReservationPublic(PublicOutput):
    folio: str
    status: str
    status_label: str
    delivery_point_name: str
    delivery_point_reference: str
    delivery_date: str
    slot_start: str
    slot_end: str
    total_amount: float
    item_count: int
    expires_at: str
    cancel_reason: str
    items: list[ConfirmationItemPublic]


class ConfirmationSettingsPublic(PublicOutput):
    shop_name: str
    logo_url: str
    contact_whatsapp: str
    delivery_instructions: str
    reservation_policy: str


class BankDetailsPublic(PublicOutput):
    bank_name: str
    account_holder: str
    clabe: str
    account_number: str
    transfer_instructions: str


class PublicConfirmationResponse(PublicOutput):
    reservation: ConfirmationReservationPublic
    settings: ConfirmationSettingsPublic
    bank_details: BankDetailsPublic


class ContentPublicResponse(PublicOutput):
    shop_name: str
    how_it_works: str
    faq_content: str
    privacy_policy: str
    reservation_policy: str
    delivery_instructions: str
