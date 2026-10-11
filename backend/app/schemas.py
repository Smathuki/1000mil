from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import BlockSource, CancellationPolicy, PropertyKind, TaskKind
from .services.markets import MARKETS


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _market(v: str) -> str:
    if v not in MARKETS:
        raise ValueError(f"Unknown market. Use one of: {', '.join(MARKETS)}")
    return v


class Photo(BaseModel):
    url: str
    room: str
    verified: bool = False


class PropertyIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    kind: PropertyKind
    city: str
    neighbourhood: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    description: str = ""
    bedrooms: int = Field(ge=0, le=40)
    bathrooms: int = Field(ge=0, le=40)
    max_guests: int = Field(ge=1, le=60)
    base_rate_cents: int = Field(ge=5000, description="Base nightly rate in US cents (≥ $50)")
    cleaning_fee_cents: int = Field(default=0, ge=0)
    min_nights: int = Field(default=1, ge=1, le=30)
    cancellation_policy: CancellationPolicy = CancellationPolicy.moderate
    amenities: list[str] = []
    power_backup: Literal["none", "generator", "solar", "inverter", "hybrid"] = "none"
    water_backup: bool = False
    security: list[str] = []
    staff: list[str] = []
    wifi_mbps: int = Field(default=0, ge=0)
    photos: list[Photo] = []
    smart_lock: bool = False

    _city = field_validator("city")(_market)


class PropertyPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    base_rate_cents: int | None = Field(default=None, ge=5000)
    cleaning_fee_cents: int | None = Field(default=None, ge=0)
    min_nights: int | None = Field(default=None, ge=1, le=30)
    max_guests: int | None = Field(default=None, ge=1, le=60)
    cancellation_policy: CancellationPolicy | None = None
    amenities: list[str] | None = None
    power_backup: Literal["none", "generator", "solar", "inverter", "hybrid"] | None = None
    water_backup: bool | None = None
    security: list[str] | None = None
    staff: list[str] | None = None
    wifi_mbps: int | None = Field(default=None, ge=0)
    photos: list[Photo] | None = None
    smart_lock: bool | None = None
    lat: float | None = None
    lng: float | None = None


class PropertyCard(ORM):
    id: int
    slug: str
    name: str
    kind: PropertyKind
    city: str
    country: str
    neighbourhood: str | None
    bedrooms: int
    bathrooms: int
    max_guests: int
    base_rate_cents: int
    photos: list[dict]
    power_backup: str
    security: list[str]
    staff: list[str]
    quality_score: float | None
    status: str


class PropertyDetail(PropertyCard):
    description: str
    lat: float | None
    lng: float | None
    amenities: list[str]
    water_backup: bool
    wifi_mbps: int
    min_nights: int
    cleaning_fee_cents: int
    cancellation_policy: CancellationPolicy
    readiness_score: int
    smart_lock: bool


class OwnerProperty(PropertyDetail):
    status_reason: str | None


class SearchResult(BaseModel):
    property: PropertyCard
    nightly_avg_cents: int
    accommodation_cents: int
    signals: list[str]


class QuoteIn(BaseModel):
    property_id: int
    check_in: date
    check_out: date
    guests: int = Field(ge=1, le=60)


class BookingIn(QuoteIn):
    airport_transfer: bool = False
    special_requests: str | None = Field(default=None, max_length=1000)


class Leg(BaseModel):
    property_id: int
    check_in: date
    check_out: date
    guests: int = Field(ge=1, le=60)
    airport_transfer: bool = False
    special_requests: str | None = None


class PackageIn(BaseModel):
    legs: list[Leg] = Field(min_length=2, max_length=6)


class BookingOut(ORM):
    id: int
    code: str
    property_id: int
    package_id: int | None
    check_in: date
    check_out: date
    guests: int
    nightly: list[dict]
    accommodation_cents: int
    cleaning_fee_cents: int
    service_fee_cents: int
    discount_cents: int
    total_cents: int
    refunded_cents: int
    cancellation_policy: CancellationPolicy
    status: str
    escrow: str
    airport_transfer: bool
    created_at: datetime


class OwnerBookingOut(BookingOut):
    commission_cents: int
    owner_payout_cents: int


class PackageOut(ORM):
    id: int
    code: str
    total_cents: int
    discount_cents: int
    status: str
    bookings: list[BookingOut]


class PaymentIn(BaseModel):
    method: Literal["mpesa", "card"]
    booking_id: int | None = None
    package_id: int | None = None
    phone: str | None = None
    card_token: str | None = None


class PaymentOut(ORM):
    id: int
    method: str
    status: str
    currency: str
    amount_local: int
    amount_cents_usd: int
    provider_ref: str | None
    receipt: str | None
    failure_reason: str | None


class BlockIn(BaseModel):
    start: date
    end: date
    source: Literal["owner", "maintenance", "whatsapp"] = "owner"
    note: str | None = None


class FeedIn(BaseModel):
    channel: Literal["airbnb", "booking_com"]
    ical_url: str


class IcalImportIn(BaseModel):
    channel: Literal["airbnb", "booking_com"]
    ical: str


class SignalIn(BaseModel):
    name: str
    city: str
    kind: Literal["conference", "safari", "holiday", "diaspora", "sports", "flights", "corporate"]
    start: date
    end: date
    intensity: float = Field(ge=0, le=1)
    source: str = "manual"

    _city = field_validator("city")(_market)


class TaskOut(ORM):
    id: int
    property_id: int
    property_name: str
    property_city: str
    property_location: list[float] | None
    booking_id: int | None
    kind: TaskKind
    title: str
    due_at: datetime
    status: str
    partner_id: int | None
    requires_photo: bool
    checkin_distance_m: float | None
    started_at: datetime | None
    completed_at: datetime | None
    proof_photos: list[str]
    notes: str | None
    rating: int | None


class TaskIn(BaseModel):
    property_id: int
    kind: TaskKind
    title: str
    due_at: datetime
    notes: str | None = None


class CheckInIn(BaseModel):
    lat: float
    lng: float


class CompleteIn(BaseModel):
    photos: list[str] = []
    notes: str | None = None


class VerifyIn(BaseModel):
    rating: int = Field(ge=1, le=5)


class PartnerOut(ORM):
    id: int
    name: str
    skills: list[str]
    city: str
    rating: float
    jobs_done: int
    active: bool


class Reading(BaseModel):
    metric: str
    value: str | float | int
    recorded_at: datetime | None = None


class TelemetryIn(BaseModel):
    readings: list[Reading] = Field(min_length=1, max_length=500)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=4000)


class UpsellIn(BaseModel):
    sku: str
    scheduled_for: datetime | None = None


class SupportIn(BaseModel):
    category: Literal["access", "power", "water", "security", "cleanliness", "transport", "other"]
    message: str = Field(min_length=2, max_length=2000)


class UserOut(ORM):
    id: int
    name: str
    email: str
    role: str
    full_service: bool


class BlockOut(ORM):
    id: int
    start: date
    end: date
    source: BlockSource
    note: str | None
