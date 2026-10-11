from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models import Booking, BookingStatus, CancellationPolicy, OpsTask
from app.services.fees import refund_fraction

from .conftest import ADMIN, GUEST, free_window, future, prop_id


def _book(client, pid, check_in, check_out, guests=2, **extra):
    return client.post("/api/bookings", headers=GUEST,
                       json={"property_id": pid, "check_in": check_in, "check_out": check_out, "guests": guests, **extra})


def test_quote_hides_owner_economics(client):
    pid = prop_id(client, "Westlands Sky Residence")
    ci, co = free_window(client, pid)
    q = client.post("/api/quote", json={"property_id": pid, "check_in": ci, "check_out": co, "guests": 2}).json()
    assert q["available"] is True
    assert len(q["nights"]) == 3
    assert "commission_cents" not in q and "owner_payout_cents" not in q
    assert q["total_cents"] == q["accommodation_cents"] + q["cleaning_fee_cents"] + q["service_fee_cents"]
    assert q["local"]["currency"] == "KES"


def test_mpesa_booking_end_to_end(client, db):
    pid = prop_id(client, "Westlands Sky Residence")
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co, airport_transfer=True).json()
    assert b["status"] == "pending_payment"

    # Dates are held while the guest pays — nobody else can take them.
    clash = client.post("/api/bookings", headers=ADMIN,
                        json={"property_id": pid, "check_in": ci, "check_out": co, "guests": 2})
    assert clash.status_code == 409

    pay = client.post("/api/payments", headers=GUEST, json={"method": "mpesa", "booking_id": b["id"], "phone": "0712 345 678"})
    assert pay.status_code == 201, pay.text
    payment = pay.json()
    assert payment["currency"] == "KES" and payment["status"] == "pending"

    done = client.post(f"/api/payments/{payment['id']}/simulate", headers=GUEST).json()
    assert done["status"] == "succeeded" and done["receipt"]

    db.expire_all()
    booking = db.scalar(select(Booking).where(Booking.code == b["code"]))
    assert booking.status == BookingStatus.confirmed
    assert booking.escrow.value == "held"
    kinds = sorted(t.kind.value for t in db.scalars(select(OpsTask).where(OpsTask.booking_id == booking.id)))
    assert kinds == ["cleaning", "cleaning", "inspection", "linen", "transfer"]
    assert all(t.partner_id for t in db.scalars(select(OpsTask).where(OpsTask.booking_id == booking.id)))

    # Callback replay is idempotent.
    again = client.post(f"/api/payments/{payment['id']}/simulate", headers=GUEST).json()
    assert again["status"] == "succeeded"
    assert client.post("/api/payments", headers=GUEST, json={"method": "card", "booking_id": b["id"], "card_token": "tok_success"}).status_code == 402


def test_failed_mpesa_keeps_booking_pending(client):
    pid = prop_id(client, "Kigali Executive Suites")
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co).json()
    pay = client.post("/api/payments", headers=GUEST, json={"method": "mpesa", "booking_id": b["id"], "phone": "0712345678"}).json()
    failed = client.post(f"/api/payments/{pay['id']}/simulate", params={"success": False}, headers=GUEST).json()
    assert failed["status"] == "failed"
    assert client.get("/api/me/bookings", headers=GUEST).json()[0]["status"] in ("pending_payment",)


def test_invalid_phone_rejected(client):
    pid = prop_id(client, "Kigali Executive Suites")
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co).json()
    r = client.post("/api/payments", headers=GUEST, json={"method": "mpesa", "booking_id": b["id"], "phone": "12345"})
    assert r.status_code == 402


def test_underpaid_callback_does_not_confirm(client, db):
    pid = prop_id(client, "Kigali Executive Suites")
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co).json()
    pay = client.post("/api/payments", headers=GUEST, json={"method": "mpesa", "booking_id": b["id"], "phone": "0712345678"}).json()
    payload = {"Body": {"stkCallback": {"CheckoutRequestID": pay["provider_ref"], "ResultCode": 0, "CallbackMetadata": {
        "Item": [{"Name": "Amount", "Value": 1}, {"Name": "MpesaReceiptNumber", "Value": "X"}]}}}}
    assert client.post("/api/payments/mpesa/callback", json=payload).status_code == 200
    assert client.get(f"/api/payments/{pay['id']}", headers=GUEST).json()["status"] == "failed"


def test_validation_rules(client):
    pid = prop_id(client, "Mara River Private Camp")  # 2-night minimum, sleeps 8
    ci, _ = free_window(client, pid)
    one_night = (date.fromisoformat(ci) + timedelta(days=1)).isoformat()
    assert _book(client, pid, ci, one_night).status_code == 409
    assert _book(client, pid, ci, (date.fromisoformat(ci) + timedelta(days=3)).isoformat(), guests=20).status_code == 409
    past = (date.today() - timedelta(days=3)).isoformat()
    assert _book(client, pid, past, ci).status_code == 409


def test_cancel_releases_dates_and_tasks(client, db):
    pid = prop_id(client, "Westlands Sky Residence")  # flexible policy
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co).json()
    client.post("/api/payments", headers=GUEST, json={"method": "card", "booking_id": b["id"], "card_token": "tok_success"})
    r = client.post(f"/api/bookings/{b['code']}/cancel", headers=GUEST).json()
    assert r["refund_fraction"] == 1.0 and r["refund_cents"] == b["total_cents"]
    db.expire_all()
    assert all(t.status.value == "cancelled" for t in db.scalars(select(OpsTask).where(OpsTask.booking_id == b["id"])))
    assert _book(client, pid, ci, co).status_code == 201  # dates back on the market


def test_refund_policies():
    booked = datetime(2026, 1, 1)
    now = datetime(2026, 1, 10)
    assert refund_fraction(CancellationPolicy.flexible, date(2026, 1, 11), booked, now) == 1.0
    assert refund_fraction(CancellationPolicy.flexible, date(2026, 1, 10), booked, now) == 0.5
    assert refund_fraction(CancellationPolicy.moderate, date(2026, 1, 13), booked, now) == 0.5
    assert refund_fraction(CancellationPolicy.moderate, date(2026, 1, 20), booked, now) == 1.0
    assert refund_fraction(CancellationPolicy.strict, date(2026, 1, 30), booked, now) == 0.5
    assert refund_fraction(CancellationPolicy.strict, date(2026, 1, 12), booked, now) == 0.0
    assert refund_fraction(CancellationPolicy.strict, date(2026, 2, 1), now, now) == 1.0  # 48h grace


def test_guest_app_and_upsells(client):
    pid = prop_id(client, "Nungwi Ocean Villa")
    ci, co = free_window(client, pid, start_after=1)
    b = _book(client, pid, ci, co).json()
    client.post("/api/payments", headers=GUEST, json={"method": "card", "booking_id": b["id"], "card_token": "tok_success"})
    stay = client.get(f"/api/stay/{b['code']}", headers=GUEST).json()
    skus = {u["sku"] for u in stay["upsells"]}
    assert "dhow_cruise" in skus and "game_drive" not in skus
    assert stay["unit_status"]["power"]["source"] is not None
    up = client.post(f"/api/stay/{b['code']}/upsells", headers=GUEST, json={"sku": "dhow_cruise"})
    assert up.status_code == 201 and up.json()["status"] == "scheduled"
    t = client.post(f"/api/stay/{b['code']}/support", headers=GUEST, json={"category": "power", "message": "Lights out"})
    assert t.json()["priority"] == "urgent"
    # Other guests can't see the stay.
    assert client.get(f"/api/stay/{b['code']}", headers={"Authorization": "Bearer demo-owner"}).status_code == 404


def test_review_requires_stay(client):
    pid = prop_id(client, "Westlands Sky Residence")
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co).json()
    assert client.post(f"/api/bookings/{b['code']}/review", headers=GUEST, json={"rating": 5}).status_code == 409


def test_expired_hold_frees_dates(client, db):
    from app.models import CalendarBlock, utcnow

    pid = prop_id(client, "Westlands Sky Residence")
    ci, co = free_window(client, pid)
    b = _book(client, pid, ci, co).json()
    hold = db.scalar(select(CalendarBlock).where(CalendarBlock.booking_id == b["id"]))
    hold.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.post("/api/bookings", headers=ADMIN,
                       json={"property_id": pid, "check_in": ci, "check_out": co, "guests": 2}).status_code == 201
    # Late payment on the lapsed booking is refunded rather than double-booking.
    pay = client.post("/api/payments", headers=GUEST, json={"method": "card", "booking_id": b["id"], "card_token": "tok_success"}).json()
    assert pay["status"] == "refunded"


def test_unknown_market_and_bad_dates(client):
    assert client.get("/api/search", params={"city": "lagos", "check_in": str(future(3)), "check_out": str(future(5))}).status_code == 404
    assert client.get("/api/search", params={"city": "nairobi", "check_in": str(future(5)), "check_out": str(future(3))}).status_code == 400
