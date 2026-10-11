"""Quotes, instant bookings, multi-property itineraries, cancellation and escrow.

Lifecycle:
  quote → create (dates held for `hold_minutes`, status pending_payment)
        → payment succeeds → confirmed (hold becomes a booking block, escrow held, run-sheet created)
        → checked_in → escrow released to owner 24h after check-in → completed
  cancel at any point before check-in → refund per policy, dates and tasks released.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    BlockSource,
    Booking,
    BookingStatus,
    CalendarBlock,
    EscrowStatus,
    Package,
    Property,
    PropertyStatus,
    User,
    utcnow,
)
from . import availability, operations
from .fees import owner_take_rate, refund_fraction
from .markets import get_market, to_local
from .pricing import price_stay

BOOKABLE = (PropertyStatus.active, PropertyStatus.coaching)
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class BookingError(Exception):
    pass


def new_code(prefix: str) -> str:
    return prefix + "".join(secrets.choice(_ALPHABET) for _ in range(6))


def validate_stay(prop: Property, check_in: date, check_out: date, guests: int, today: date) -> None:
    if prop.status not in BOOKABLE:
        raise BookingError(f"{prop.name} is not currently bookable")
    if check_in < today:
        raise BookingError("Check-in cannot be in the past")
    if check_out <= check_in:
        raise BookingError("Check-out must be after check-in")
    nights = (check_out - check_in).days
    if nights < prop.min_nights:
        raise BookingError(f"{prop.name} has a {prop.min_nights}-night minimum")
    if nights > 90:
        raise BookingError("Stays longer than 90 nights are handled by the corporate desk")
    if guests < 1 or guests > prop.max_guests:
        raise BookingError(f"{prop.name} sleeps up to {prop.max_guests} guests")


def quote(
    db: Session,
    prop: Property,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    today: date | None = None,
    discount_rate: float = 0.0,
) -> dict:
    today = today or utcnow().date()
    validate_stay(prop, check_in, check_out, guests, today)
    nights = price_stay(db, prop, check_in, check_out, today=today)
    accommodation = sum(n.price_cents for n in nights)
    discount = int(round(accommodation * discount_rate))
    service_fee = int(round((accommodation - discount) * settings.guest_service_fee_rate))
    total = accommodation - discount + prop.cleaning_fee_cents + service_fee
    commission = int(round((accommodation - discount + prop.cleaning_fee_cents) * owner_take_rate(prop.owner)))
    market = get_market(prop.city)
    return {
        "property_id": prop.id,
        "property_name": prop.name,
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "guests": guests,
        "nights": [n.as_dict() for n in nights],
        "accommodation_cents": accommodation,
        "discount_cents": discount,
        "cleaning_fee_cents": prop.cleaning_fee_cents,
        "service_fee_cents": service_fee,
        "total_cents": total,
        "commission_cents": commission,
        "owner_payout_cents": total - service_fee - commission,
        "currency": "USD",
        "local": {"currency": market.currency, "total": to_local(total, market.currency)},
        "cancellation_policy": prop.cancellation_policy.value,
        "available": availability.is_available(db, prop.id, check_in, check_out),
    }


def _create_leg(
    db: Session,
    guest: User,
    prop: Property,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    today: date,
    discount_rate: float,
    airport_transfer: bool,
    special_requests: str | None,
    channel: str,
    package: Package | None,
) -> Booking:
    q = quote(db, prop, check_in, check_out, guests, today=today, discount_rate=discount_rate)
    if not q["available"]:
        raise BookingError(f"{prop.name} is no longer available for those dates")
    booking = Booking(
        code=new_code("MK"),
        guest_id=guest.id,
        property_id=prop.id,
        package_id=package.id if package else None,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        nightly=q["nights"],
        accommodation_cents=q["accommodation_cents"],
        cleaning_fee_cents=q["cleaning_fee_cents"],
        service_fee_cents=q["service_fee_cents"],
        discount_cents=q["discount_cents"],
        total_cents=q["total_cents"],
        commission_cents=q["commission_cents"],
        owner_payout_cents=q["owner_payout_cents"],
        cancellation_policy=prop.cancellation_policy,
        airport_transfer=airport_transfer,
        special_requests=special_requests,
        channel=channel,
    )
    db.add(booking)
    db.flush()
    try:
        availability.add_block(
            db,
            prop,
            check_in,
            check_out,
            BlockSource.hold,
            booking_id=booking.id,
            expires_at=utcnow() + timedelta(minutes=settings.hold_minutes),
            note=f"Payment hold {booking.code}",
        )
    except availability.Unavailable as exc:
        raise BookingError(str(exc)) from exc
    return booking


def create_booking(
    db: Session,
    guest: User,
    prop: Property,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    airport_transfer: bool = False,
    special_requests: str | None = None,
    channel: str = "web",
    today: date | None = None,
) -> Booking:
    availability.purge_expired_holds(db)
    return _create_leg(
        db,
        guest,
        prop,
        check_in,
        check_out,
        guests,
        today=today or utcnow().date(),
        discount_rate=0.0,
        airport_transfer=airport_transfer,
        special_requests=special_requests,
        channel=channel,
        package=None,
    )


def package_discount_rate(legs: int) -> float:
    return settings.package_discount_rate if legs >= 3 else 0.0


def validate_itinerary(legs: list[dict]) -> list[dict]:
    if len(legs) < 2:
        raise BookingError("An itinerary needs at least two stays")
    ordered = sorted(legs, key=lambda leg: leg["check_in"])
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        if nxt["check_in"] < prev["check_out"]:
            raise BookingError("Itinerary stays overlap")
    return ordered


def create_package(
    db: Session, guest: User, legs: list[dict], *, channel: str = "web", today: date | None = None
) -> Package:
    """All-or-nothing: every leg is held, or none is (caller rolls back on BookingError)."""
    availability.purge_expired_holds(db)
    today = today or utcnow().date()
    ordered = validate_itinerary(legs)
    rate = package_discount_rate(len(ordered))
    package = Package(code=new_code("PK"), guest_id=guest.id, total_cents=0)
    db.add(package)
    db.flush()
    for i, leg in enumerate(ordered):
        prop = db.get(Property, leg["property_id"])
        if prop is None:
            raise BookingError(f"Unknown property {leg['property_id']}")
        _create_leg(
            db,
            guest,
            prop,
            leg["check_in"],
            leg["check_out"],
            leg["guests"],
            today=today,
            discount_rate=rate,
            # Transfers between legs are arranged for every leg after the first; first leg on request.
            airport_transfer=bool(leg.get("airport_transfer")) or i > 0,
            special_requests=leg.get("special_requests"),
            channel=channel,
            package=package,
        )
    db.flush()
    db.refresh(package)
    package.discount_cents = sum(b.discount_cents for b in package.bookings)
    package.total_cents = sum(b.total_cents for b in package.bookings)
    return package


def confirm(db: Session, booking: Booking) -> Booking:
    """Payment received: lock dates, hold funds in escrow, spin up the ops run-sheet."""
    if booking.status == BookingStatus.confirmed:
        return booking
    if booking.status not in (BookingStatus.pending_payment, BookingStatus.expired):
        raise BookingError(f"Cannot confirm a booking that is {booking.status.value}")
    hold = db.scalar(
        select(CalendarBlock).where(CalendarBlock.booking_id == booking.id, CalendarBlock.source == BlockSource.hold)
    )
    if hold is not None:
        hold.source, hold.expires_at, hold.note = BlockSource.booking, None, f"Booking {booking.code}"
    else:
        # Hold lapsed while the guest paid. Re-take the dates if still free; otherwise refund.
        try:
            availability.add_block(
                db, booking.property, booking.check_in, booking.check_out, BlockSource.booking,
                booking_id=booking.id, note=f"Booking {booking.code}",
            )
        except availability.Unavailable as exc:
            booking.status = BookingStatus.cancelled
            booking.escrow = EscrowStatus.refunded
            booking.refunded_cents = booking.total_cents
            raise BookingError("Dates were taken after the payment hold expired; payment refunded") from exc
    booking.status = BookingStatus.confirmed
    booking.escrow = EscrowStatus.held
    booking.confirmed_at = utcnow()
    db.flush()
    operations.tasks_for_booking(db, booking)
    return booking


def confirm_package(db: Session, package: Package) -> Package:
    """An itinerary is confirmed whole or refunded whole — a guest never ends up with half a trip."""
    try:
        for b in package.bookings:
            confirm(db, b)
    except BookingError:
        for b in package.bookings:
            if b.status == BookingStatus.confirmed:
                cancel(db, b)
                b.escrow, b.refunded_cents = EscrowStatus.refunded, b.total_cents
                b.owner_payout_cents = b.commission_cents = 0
            elif b.status in (BookingStatus.pending_payment, BookingStatus.expired):
                for block in db.scalars(select(CalendarBlock).where(CalendarBlock.booking_id == b.id)):
                    db.delete(block)
                b.status, b.escrow, b.refunded_cents = BookingStatus.cancelled, EscrowStatus.refunded, b.total_cents
        package.status = BookingStatus.cancelled
        raise
    package.status = BookingStatus.confirmed
    return package


def cancel(db: Session, booking: Booking, *, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if booking.status in (BookingStatus.cancelled, BookingStatus.expired, BookingStatus.completed):
        raise BookingError(f"Booking is already {booking.status.value}")
    if booking.status == BookingStatus.checked_in:
        raise BookingError("Stays in progress are handled by the concierge desk")
    paid = booking.status == BookingStatus.confirmed
    fraction = refund_fraction(booking.cancellation_policy, booking.check_in, booking.created_at, now) if paid else 0.0
    refund = int(round(booking.total_cents * fraction))
    for block in db.scalars(select(CalendarBlock).where(CalendarBlock.booking_id == booking.id)):
        db.delete(block)
    operations.cancel_booking_tasks(db, booking)
    booking.status = BookingStatus.cancelled
    booking.refunded_cents = refund
    if paid:
        booking.escrow = EscrowStatus.refunded if fraction == 1.0 else EscrowStatus.partially_refunded
        # Owner keeps their share of the retained amount; platform keeps its proportional commission.
        retained = booking.total_cents - refund
        share = retained / booking.total_cents if booking.total_cents else 0
        booking.owner_payout_cents = int(round(booking.owner_payout_cents * share))
        booking.commission_cents = int(round(booking.commission_cents * share))
    return {"refund_cents": refund, "refund_fraction": fraction}


def check_in_guest(db: Session, booking: Booking, *, today: date | None = None) -> Booking:
    today = today or utcnow().date()
    if booking.status != BookingStatus.confirmed:
        raise BookingError("Only confirmed bookings can check in")
    if not booking.check_in <= today < booking.check_out:
        raise BookingError("Check-in is only possible during the stay window")
    booking.status = BookingStatus.checked_in
    return booking


def release_due_escrow(db: Session, *, now: datetime | None = None) -> list[Booking]:
    """Owners are paid out 24h after a successful check-in (escrow protects both sides of high-value stays)."""
    now = now or utcnow()
    released = []
    stmt = select(Booking).where(
        Booking.escrow == EscrowStatus.held,
        Booking.status.in_([BookingStatus.checked_in, BookingStatus.completed]),
    )
    for b in db.scalars(stmt):
        if now >= datetime.combine(b.check_in, datetime.min.time()) + timedelta(days=1):
            b.escrow = EscrowStatus.released
            released.append(b)
    return released


def expire_unpaid(db: Session) -> int:
    """Bookings whose hold lapsed without payment are expired so the dates return to the market."""
    availability.purge_expired_holds(db)
    stale = db.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.pending_payment,
            Booking.created_at < utcnow() - timedelta(minutes=settings.hold_minutes),
        )
    )
    count = 0
    for b in stale:
        b.status = BookingStatus.expired
        count += 1
    return count
