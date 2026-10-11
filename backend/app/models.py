"""Domain model for the flexible luxury inventory network.

Money is stored as integer US cents (`*_cents`) to avoid float drift; local-currency
amounts (KES, TZS, RWF, UGX) are derived at quote/payment time via `services.fx`.
Calendar ranges are half-open: [start, end) — `end` is the checkout date.
"""

from __future__ import annotations

import builtins
import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Role(str, enum.Enum):
    guest = "guest"
    owner = "owner"
    partner = "partner"
    admin = "admin"


class PropertyKind(str, enum.Enum):
    villa = "villa"
    apartment = "apartment"
    lodge = "lodge"
    residence = "residence"
    tented_camp = "tented_camp"


class PropertyStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    coaching = "coaching"  # live, but flagged for quality improvement
    suspended = "suspended"  # temporarily delisted


class CancellationPolicy(str, enum.Enum):
    flexible = "flexible"
    moderate = "moderate"
    strict = "strict"


class BlockSource(str, enum.Enum):
    owner = "owner"
    booking = "booking"
    hold = "hold"
    airbnb = "airbnb"
    booking_com = "booking_com"
    whatsapp = "whatsapp"
    maintenance = "maintenance"


class BookingStatus(str, enum.Enum):
    pending_payment = "pending_payment"
    confirmed = "confirmed"
    checked_in = "checked_in"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"


class EscrowStatus(str, enum.Enum):
    none = "none"
    held = "held"
    released = "released"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class TaskKind(str, enum.Enum):
    cleaning = "cleaning"
    linen = "linen"
    inspection = "inspection"
    security = "security"
    transfer = "transfer"
    chef = "chef"
    concierge = "concierge"
    maintenance = "maintenance"


class TaskStatus(str, enum.Enum):
    open = "open"
    assigned = "assigned"
    in_progress = "in_progress"
    done = "done"
    verified = "verified"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[Role] = mapped_column(Enum(Role))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kyc_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    full_service: Mapped[bool] = mapped_column(Boolean, default=False)  # owner opted into white-label ops
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    kind: Mapped[PropertyKind] = mapped_column(Enum(PropertyKind))
    city: Mapped[str] = mapped_column(String(80), index=True)  # market key, e.g. "nairobi", "maasai-mara"
    country: Mapped[str] = mapped_column(String(2))  # ISO-3166 alpha-2
    neighbourhood: Mapped[str | None] = mapped_column(String(120))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")
    bedrooms: Mapped[int] = mapped_column(Integer, default=1)
    bathrooms: Mapped[int] = mapped_column(Integer, default=1)
    max_guests: Mapped[int] = mapped_column(Integer, default=2)
    base_rate_cents: Mapped[int] = mapped_column(Integer)
    cleaning_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    min_nights: Mapped[int] = mapped_column(Integer, default=1)
    cancellation_policy: Mapped[CancellationPolicy] = mapped_column(
        Enum(CancellationPolicy), default=CancellationPolicy.moderate
    )
    # Structured capture used for the "hotel-ready" assessment.
    amenities: Mapped[list] = mapped_column(JSON, default=list)
    power_backup: Mapped[str] = mapped_column(String(20), default="none")  # none|generator|solar|inverter|hybrid
    water_backup: Mapped[bool] = mapped_column(Boolean, default=False)
    security: Mapped[list] = mapped_column(JSON, default=list)  # guard_24h, cctv, gated, alarm, safe
    staff: Mapped[list] = mapped_column(JSON, default=list)  # housekeeper, chef, butler, driver, guide
    wifi_mbps: Mapped[int] = mapped_column(Integer, default=0)
    photos: Mapped[list] = mapped_column(JSON, default=list)  # [{url, room, verified}]
    smart_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    device_key_hash: Mapped[str | None] = mapped_column(String(64))  # IoT gateway credential

    status: Mapped[PropertyStatus] = mapped_column(Enum(PropertyStatus), default=PropertyStatus.draft)
    status_reason: Mapped[str | None] = mapped_column(String(300))
    readiness_score: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User] = relationship()
    blocks: Mapped[list[CalendarBlock]] = relationship(back_populates="property", cascade="all, delete-orphan")
    feeds: Mapped[list[ChannelFeed]] = relationship(back_populates="property", cascade="all, delete-orphan")


class CalendarBlock(Base):
    __tablename__ = "calendar_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)  # exclusive
    source: Mapped[BlockSource] = mapped_column(Enum(BlockSource))
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    external_uid: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # set for payment holds
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    property: Mapped[Property] = relationship(back_populates="blocks")


class ChannelFeed(Base):
    """An external calendar (Airbnb / Booking.com iCal) that we import and mirror as blocks."""

    __tablename__ = "channel_feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    channel: Mapped[BlockSource] = mapped_column(Enum(BlockSource))
    ical_url: Mapped[str] = mapped_column(String(500))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_result: Mapped[str | None] = mapped_column(String(255))

    property: Mapped[Property] = relationship(back_populates="feeds")


class DemandSignal(Base):
    """A real-world demand driver: conference, migration season, diaspora homecoming, flight surge."""

    __tablename__ = "demand_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # conference|safari|holiday|diaspora|sports|flights|corporate
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)  # exclusive
    intensity: Mapped[float] = mapped_column(Float)  # 0..1 strength of expected demand uplift
    source: Mapped[str] = mapped_column(String(80), default="manual")


class SearchLog(Base):
    """Anonymous search events; feeds unmet-demand insights."""

    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(80), index=True)
    check_in: Mapped[date] = mapped_column(Date)
    nights: Mapped[int] = mapped_column(Integer)
    guests: Mapped[int] = mapped_column(Integer)
    results: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(20), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Package(Base):
    """A multi-property itinerary paid and managed as one booking."""

    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.pending_payment)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    bookings: Mapped[list[Booking]] = relationship(back_populates="package", order_by="Booking.check_in")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    guests: Mapped[int] = mapped_column(Integer)
    nightly: Mapped[list] = mapped_column(JSON)  # [{date, price_cents, factors}]
    accommodation_cents: Mapped[int] = mapped_column(Integer)
    cleaning_fee_cents: Mapped[int] = mapped_column(Integer)
    service_fee_cents: Mapped[int] = mapped_column(Integer)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer)
    commission_cents: Mapped[int] = mapped_column(Integer)  # platform take from owner side
    owner_payout_cents: Mapped[int] = mapped_column(Integer)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    cancellation_policy: Mapped[CancellationPolicy] = mapped_column(Enum(CancellationPolicy))
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.pending_payment)
    escrow: Mapped[EscrowStatus] = mapped_column(Enum(EscrowStatus), default=EscrowStatus.none)
    airport_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    special_requests: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)

    guest: Mapped[User] = relationship()
    property: Mapped[Property] = relationship()
    package: Mapped[Package | None] = relationship(back_populates="bookings")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    method: Mapped[str] = mapped_column(String(20))  # mpesa|card
    amount_cents_usd: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    amount_local: Mapped[int] = mapped_column(Integer)  # whole units of `currency` (M-Pesa takes integers)
    phone: Mapped[str | None] = mapped_column(String(20))
    provider_ref: Mapped[str | None] = mapped_column(String(80), index=True)
    receipt: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.pending)
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Partner(Base):
    """A verified local service provider: housekeeper, driver, chef, guide, security."""

    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    skills: Mapped[list] = mapped_column(JSON)
    city: Mapped[str] = mapped_column(String(80), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    ratings_count: Mapped[int] = mapped_column(Integer, default=0)
    jobs_done: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship()


class OpsTask(Base):
    __tablename__ = "ops_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    kind: Mapped[TaskKind] = mapped_column(Enum(TaskKind))
    title: Mapped[str] = mapped_column(String(200))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.open)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"))
    requires_photo: Mapped[bool] = mapped_column(Boolean, default=True)
    checkin_lat: Mapped[float | None] = mapped_column(Float)
    checkin_lng: Mapped[float | None] = mapped_column(Float)
    checkin_distance_m: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    proof_photos: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    property: Mapped[Property] = relationship()
    partner: Mapped[Partner | None] = relationship()

    # Denormalised for the partner app, which has no access to owner/property endpoints.
    @builtins.property
    def property_name(self) -> str:
        return self.property.name

    @builtins.property
    def property_city(self) -> str:
        return self.property.city

    @builtins.property
    def property_location(self) -> list[float] | None:
        p = self.property
        return [p.lat, p.lng] if p.lat is not None and p.lng is not None else None


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    metric: Mapped[str] = mapped_column(String(30))  # power_source|battery_pct|fuel_pct|water_pct|alarm|door|occupancy
    value: Mapped[str] = mapped_column(String(60))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    aspects: Mapped[dict] = mapped_column(JSON, default=dict)  # extracted aspect sentiment
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Upsell(Base):
    __tablename__ = "upsells"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    sku: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    price_cents: Mapped[int] = mapped_column(Integer)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="requested")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("ops_tasks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    category: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MessageLog(Base):
    """Inbound/outbound WhatsApp / Telegram messages (sandbox mode keeps them here instead of sending)."""

    __tablename__ = "message_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(3))  # in|out
    peer: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
