"""Payments over local rails (M-Pesa STK push) and international cards.

`sandbox` mode never leaves the process: STK pushes get a synthetic CheckoutRequestID and are
settled by posting a Daraja-shaped callback (the frontend's "simulate" button does exactly that),
so the full confirm → escrow → ops path is exercised end to end. `live` mode calls Daraja.
Card acquiring is a provider slot (Flutterwave / DPO / Stripe); sandbox accepts test tokens.
"""

from __future__ import annotations

import base64
import secrets
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Booking, Package, Payment, PaymentStatus
from . import booking as booking_svc
from .markets import to_local


class PaymentError(Exception):
    pass


def normalize_msisdn(phone: str) -> str:
    """Accept 07XX…, 01XX…, +2547XX…, 2547XX… and return 2547XXXXXXXX as Daraja requires."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if not (digits.startswith("254") and len(digits) == 12 and digits[3] in "17"):
        raise PaymentError("Enter a valid Kenyan M-Pesa number, e.g. 0712 345 678")
    return digits


def _target(db: Session, booking_id: int | None, package_id: int | None) -> tuple[str, Booking | Package]:
    if bool(booking_id) == bool(package_id):
        raise PaymentError("Pay for exactly one booking or one package")
    if package_id:
        pkg = db.get(Package, package_id)
        if pkg is None:
            raise PaymentError("Package not found")
        return pkg.code, pkg
    b = db.get(Booking, booking_id)
    if b is None:
        raise PaymentError("Booking not found")
    if b.package_id:
        raise PaymentError("This stay is part of an itinerary — pay for the package instead")
    return b.code, b


def _daraja_token() -> str:
    resp = httpx.get(
        f"{settings.mpesa_base_url}/oauth/v1/generate?grant_type=client_credentials",
        auth=(settings.mpesa_consumer_key, settings.mpesa_consumer_secret),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    return base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()


def _stk_push(phone: str, amount_kes: int, reference: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": settings.mpesa_shortcode,
        "Password": stk_password(settings.mpesa_shortcode, settings.mpesa_passkey, timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount_kes,
        "PartyA": phone,
        "PartyB": settings.mpesa_shortcode,
        "PhoneNumber": phone,
        "CallBackURL": settings.mpesa_callback_url,
        "AccountReference": reference,
        "TransactionDesc": f"Makao stay {reference}",
    }
    resp = httpx.post(
        f"{settings.mpesa_base_url}/mpesa/stkpush/v1/processrequest",
        json=body,
        headers={"Authorization": f"Bearer {_daraja_token()}"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("ResponseCode") != "0":
        raise PaymentError(data.get("errorMessage") or data.get("ResponseDescription") or "STK push rejected")
    return data["CheckoutRequestID"]


def _settle(db: Session, payment: Payment) -> None:
    if payment.package_id:
        booking_svc.confirm_package(db, db.get(Package, payment.package_id))
    else:
        booking_svc.confirm(db, db.get(Booking, payment.booking_id))


def initiate(
    db: Session,
    *,
    method: str,
    booking_id: int | None = None,
    package_id: int | None = None,
    phone: str | None = None,
    card_token: str | None = None,
) -> Payment:
    reference, target = _target(db, booking_id, package_id)
    if target.status.value not in ("pending_payment", "expired"):
        raise PaymentError(f"{reference} is {target.status.value}; nothing to pay")
    already = db.scalar(
        select(Payment).where(
            Payment.booking_id == booking_id if booking_id else Payment.package_id == package_id,
            Payment.status == PaymentStatus.succeeded,
        )
    )
    if already:
        raise PaymentError(f"{reference} is already paid")

    amount = target.total_cents
    if method == "mpesa":
        if not phone:
            raise PaymentError("Phone number required for M-Pesa")
        msisdn = normalize_msisdn(phone)
        payment = Payment(
            booking_id=booking_id, package_id=package_id, method="mpesa", amount_cents_usd=amount,
            currency="KES", amount_local=to_local(amount, "KES"), phone=msisdn,
        )
        if settings.is_sandbox_payments:
            payment.provider_ref = "ws_CO_SANDBOX_" + secrets.token_hex(8).upper()
        else:
            payment.provider_ref = _stk_push(msisdn, payment.amount_local, reference)
        db.add(payment)
        db.flush()
        return payment

    if method == "card":
        payment = Payment(
            booking_id=booking_id, package_id=package_id, method="card", amount_cents_usd=amount,
            currency="USD", amount_local=(amount + 99) // 100,
        )
        db.add(payment)
        if not settings.is_sandbox_payments:
            raise PaymentError("Card acquiring provider not configured")
        if card_token == "tok_success":
            payment.provider_ref = "ch_" + secrets.token_hex(10)
            payment.status = PaymentStatus.succeeded
            db.flush()
            try:
                _settle(db, payment)
            except booking_svc.BookingError as exc:
                payment.status, payment.failure_reason = PaymentStatus.refunded, str(exc)
        else:
            payment.status = PaymentStatus.failed
            payment.failure_reason = "Card declined"
        db.flush()
        return payment

    raise PaymentError(f"Unsupported payment method '{method}'")


def handle_mpesa_callback(db: Session, payload: dict) -> Payment | None:
    """Process Safaricom's STK callback. Idempotent: replays of a settled payment are no-ops."""
    cb = payload.get("Body", {}).get("stkCallback", {})
    checkout_id = cb.get("CheckoutRequestID")
    payment = db.scalar(select(Payment).where(Payment.provider_ref == checkout_id)) if checkout_id else None
    if payment is None or payment.status != PaymentStatus.pending:
        return payment
    if cb.get("ResultCode") != 0:
        payment.status = PaymentStatus.failed
        payment.failure_reason = cb.get("ResultDesc", "Cancelled by user")
        return payment
    meta = {i.get("Name"): i.get("Value") for i in cb.get("CallbackMetadata", {}).get("Item", [])}
    if int(meta.get("Amount") or 0) < payment.amount_local:
        payment.status = PaymentStatus.failed
        payment.failure_reason = f"Underpaid: received {meta.get('Amount')} of {payment.amount_local} KES"
        return payment
    payment.receipt = str(meta.get("MpesaReceiptNumber") or "")
    payment.status = PaymentStatus.succeeded
    try:
        _settle(db, payment)
    except booking_svc.BookingError as exc:
        # Money arrived but the stay could not be secured: settlement code already marked it refunded.
        payment.status = PaymentStatus.refunded
        payment.failure_reason = str(exc)
    return payment


def sandbox_callback_payload(payment: Payment, *, success: bool = True) -> dict:
    """Build the exact payload Daraja would POST, so sandbox exercises the real callback path."""
    cb: dict = {
        "MerchantRequestID": "sandbox-" + str(payment.id),
        "CheckoutRequestID": payment.provider_ref,
        "ResultCode": 0 if success else 1032,
        "ResultDesc": "The service request is processed successfully." if success else "Request cancelled by user",
    }
    if success:
        cb["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": payment.amount_local},
                {"Name": "MpesaReceiptNumber", "Value": "S" + secrets.token_hex(5).upper()},
                {"Name": "TransactionDate", "Value": int(datetime.now().strftime("%Y%m%d%H%M%S"))},
                {"Name": "PhoneNumber", "Value": int(payment.phone or 0)},
            ]
        }
    return {"Body": {"stkCallback": cb}}
