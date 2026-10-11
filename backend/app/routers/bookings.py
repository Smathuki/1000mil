"""Guest-side booking lifecycle, payments and the in-stay guest app."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import (
    Booking,
    BookingStatus,
    Package,
    Payment,
    Property,
    Review,
    Role,
    SupportTicket,
    TaskKind,
    Upsell,
    User,
    utcnow,
)
from ..schemas import (
    BookingIn,
    BookingOut,
    PackageIn,
    PackageOut,
    PaymentIn,
    PaymentOut,
    PropertyDetail,
    ReviewIn,
    SupportIn,
    UpsellIn,
)
from ..services import booking as booking_svc
from ..services import iot, operations, payments, quality
from ..services.concierge import RECOMMENDATIONS, UPSELLS, catalogue

router = APIRouter(tags=["bookings"])


def _guest_booking(db: Session, code: str, user: User) -> Booking:
    b = db.scalar(select(Booking).where(Booking.code == code.upper()))
    if b is None or (b.guest_id != user.id and user.role != Role.admin):
        raise HTTPException(404, "Booking not found")
    return b


@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(body: BookingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prop = db.get(Property, body.property_id)
    if prop is None:
        raise HTTPException(404, "Property not found")
    b = booking_svc.create_booking(
        db, user, prop, body.check_in, body.check_out, body.guests,
        airport_transfer=body.airport_transfer, special_requests=body.special_requests,
    )
    db.commit()
    return b


@router.post("/packages", response_model=PackageOut, status_code=201)
def create_package(body: PackageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    pkg = booking_svc.create_package(db, user, [leg.model_dump() for leg in body.legs])
    db.commit()
    return pkg


@router.get("/me/bookings", response_model=list[BookingOut])
def my_bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Booking).where(Booking.guest_id == user.id).order_by(Booking.check_in.desc())))


@router.get("/packages/{code}", response_model=PackageOut)
def get_package(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    pkg = db.scalar(select(Package).where(Package.code == code.upper()))
    if pkg is None or (pkg.guest_id != user.id and user.role != Role.admin):
        raise HTTPException(404, "Package not found")
    return pkg


@router.post("/bookings/{code}/cancel")
def cancel_booking(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _guest_booking(db, code, user)
    result = booking_svc.cancel(db, b)
    db.commit()
    return {"code": b.code, "status": b.status.value, **result}


@router.post("/bookings/{code}/check-in", response_model=BookingOut)
def check_in(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _guest_booking(db, code, user)
    booking_svc.check_in_guest(db, b)
    db.commit()
    return b


@router.post("/bookings/{code}/review")
def review(code: str, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _guest_booking(db, code, user)
    if b.status not in (BookingStatus.checked_in, BookingStatus.completed):
        raise HTTPException(409, "You can review once your stay has started")
    if db.scalar(select(Review).where(Review.booking_id == b.id)):
        raise HTTPException(409, "Already reviewed")
    aspects = quality.analyze_review(body.text)
    db.add(Review(booking_id=b.id, property_id=b.property_id, rating=body.rating, text=body.text, aspects=aspects))
    db.flush()
    result = quality.apply_quality_actions(db, b.property)
    db.commit()
    return {"aspects": aspects, "quality": result}


# ------------------------------------------------------------------ payments


@router.post("/payments", response_model=PaymentOut, status_code=201)
def pay(body: PaymentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_id = None
    if body.booking_id:
        b = db.get(Booking, body.booking_id)
        owner_id = b.guest_id if b else None
    elif body.package_id:
        p = db.get(Package, body.package_id)
        owner_id = p.guest_id if p else None
    if owner_id is None or (owner_id != user.id and user.role != Role.admin):
        raise HTTPException(404, "Nothing to pay for")
    payment = payments.initiate(
        db, method=body.method, booking_id=body.booking_id, package_id=body.package_id,
        phone=body.phone, card_token=body.card_token,
    )
    db.commit()
    return payment


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def payment_status(payment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    target = db.get(Booking, payment.booking_id) if payment.booking_id else db.get(Package, payment.package_id)
    if target.guest_id != user.id and user.role != Role.admin:
        raise HTTPException(404, "Payment not found")
    return payment


@router.post("/payments/mpesa/callback")
async def mpesa_callback(request: Request, db: Session = Depends(get_db)):
    """Safaricom posts here. Always 200 so Daraja does not retry-storm; outcome is on the payment."""
    payments.handle_mpesa_callback(db, await request.json())
    db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/payments/{payment_id}/simulate", response_model=PaymentOut)
def simulate_mpesa(
    payment_id: int, success: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Sandbox only: play the guest approving (or cancelling) the STK prompt on their phone."""
    if not settings.is_sandbox_payments:
        raise HTTPException(404, "Not found")
    payment = payment_status(payment_id, user, db)
    if payment.method != "mpesa":
        raise HTTPException(400, "Only M-Pesa payments can be simulated")
    payments.handle_mpesa_callback(db, payments.sandbox_callback_payload(payment, success=success))
    db.commit()
    return payment


# ------------------------------------------------------------------ guest app


@router.get("/stay/{code}")
def stay(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _guest_booking(db, code, user)
    prop = b.property
    now = utcnow()
    opens, closes = iot.access_window(b)
    access = None
    if b.status in (BookingStatus.confirmed, BookingStatus.checked_in) and opens - timedelta(hours=24) <= now <= closes:
        access = {
            "code": iot.access_code(b) if prop.smart_lock else None,
            "method": "smart_lock" if prop.smart_lock else "staff_handover",
            "valid_from": opens, "valid_until": closes,
        }
    return {
        "booking": BookingOut.model_validate(b).model_dump(),
        "property": PropertyDetail.model_validate(prop).model_dump(),
        "unit_status": iot.unit_status(db, prop),
        "readiness": operations.unit_ready(db, b),
        "access": access,
        "upsells": catalogue(prop.city),
        "my_upsells": [
            {"id": u.id, "title": u.title, "price_cents": u.price_cents, "status": u.status, "scheduled_for": u.scheduled_for}
            for u in db.scalars(select(Upsell).where(Upsell.booking_id == b.id))
        ],
        "tickets": [
            {"id": t.id, "category": t.category, "message": t.message, "status": t.status, "priority": t.priority,
             "created_at": t.created_at}
            for t in db.scalars(select(SupportTicket).where(SupportTicket.booking_id == b.id).order_by(SupportTicket.id.desc()))
        ],
        "recommendations": RECOMMENDATIONS.get(prop.city, []),
        "support_whatsapp": "+254700000000",
    }


@router.post("/stay/{code}/upsells", status_code=201)
def add_upsell(code: str, body: UpsellIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _guest_booking(db, code, user)
    if b.status not in (BookingStatus.confirmed, BookingStatus.checked_in):
        raise HTTPException(409, "Extras can be added to confirmed stays")
    item = {u["sku"]: u for u in catalogue(b.property.city)}.get(body.sku)
    if item is None:
        raise HTTPException(404, "Extra not available for this destination")
    when = body.scheduled_for or datetime.combine(b.check_in, datetime.min.time()) + timedelta(hours=16)
    task = operations.create_task(db, b.property, UPSELLS[body.sku]["task"], f"{item['title']} · {b.code}", when, booking=b)
    upsell = Upsell(booking_id=b.id, sku=body.sku, title=item["title"], price_cents=item["price_cents"],
                    scheduled_for=when, task_id=task.id, status="scheduled")
    db.add(upsell)
    db.commit()
    return {"id": upsell.id, "title": upsell.title, "price_cents": upsell.price_cents, "status": upsell.status,
            "scheduled_for": upsell.scheduled_for}


@router.post("/stay/{code}/support", status_code=201)
def support(code: str, body: SupportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _guest_booking(db, code, user)
    urgent = body.category in ("access", "power", "security", "water")
    ticket = SupportTicket(booking_id=b.id, category=body.category, message=body.message,
                           priority="urgent" if urgent else "normal")
    db.add(ticket)
    if urgent and b.status in (BookingStatus.confirmed, BookingStatus.checked_in):
        kind = TaskKind.security if body.category in ("security", "access") else TaskKind.maintenance
        operations.create_task(db, b.property, kind, f"Guest reported {body.category} issue · {b.code}",
                               utcnow() + timedelta(minutes=45), booking=b, notes=body.message)
    db.commit()
    return {"id": ticket.id, "priority": ticket.priority, "status": ticket.status}
