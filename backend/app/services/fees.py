"""Commercial rules: guest fees, owner commission, cancellation refunds."""

from __future__ import annotations

from datetime import date, datetime

from ..config import settings
from ..models import CancellationPolicy, User


def owner_take_rate(owner: User) -> float:
    rate = settings.default_commission_rate
    if owner.full_service:
        rate += settings.full_service_ops_rate
    return rate


def refund_fraction(policy: CancellationPolicy, check_in: date, booked_at: datetime, now: datetime) -> float:
    """Share of the paid total returned to the guest on cancellation."""
    days_out = (check_in - now.date()).days
    if days_out < 0:
        return 0.0
    if policy is CancellationPolicy.flexible:
        return 1.0 if days_out >= 1 else 0.5
    if policy is CancellationPolicy.moderate:
        return 1.0 if days_out >= 5 else 0.5
    # strict: 48h free-cancel grace if booked ≥14 days out, then 50% until 7 days, then nothing.
    if (now - booked_at).total_seconds() <= 48 * 3600 and days_out >= 14:
        return 1.0
    return 0.5 if days_out >= 7 else 0.0
