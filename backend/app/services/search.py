from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Property, PropertyKind, SearchLog, utcnow
from . import availability
from .booking import BOOKABLE, BookingError, validate_stay
from .pricing import market_occupancy, price_stay


def search(
    db: Session,
    city: str,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    kind: PropertyKind | None = None,
    max_nightly_cents: int | None = None,
    channel: str = "web",
    today: date | None = None,
) -> list[dict]:
    today = today or utcnow().date()
    stmt = select(Property).where(Property.city == city, Property.status.in_(BOOKABLE), Property.max_guests >= guests)
    if kind:
        stmt = stmt.where(Property.kind == kind)
    props = list(db.scalars(stmt))
    blocked = availability.unavailable_property_ids(db, [p.id for p in props], check_in, check_out)
    occupancy = market_occupancy(db, city, check_in, check_out)

    results = []
    for p in props:
        if p.id in blocked:
            continue
        try:
            validate_stay(p, check_in, check_out, guests, today)
        except BookingError:
            continue
        nights = price_stay(db, p, check_in, check_out, today=today, occupancy=occupancy)
        total = sum(n.price_cents for n in nights)
        avg = total // len(nights)
        if max_nightly_cents and avg > max_nightly_cents:
            continue
        results.append(
            {
                "property": p,
                "nightly_avg_cents": avg,
                "accommodation_cents": total,
                "signals": sorted({s for n in nights for s in n.signals}),
            }
        )
    results.sort(key=lambda r: (-(r["property"].quality_score or 80), r["nightly_avg_cents"]))
    db.add(
        SearchLog(
            city=city, check_in=check_in, nights=(check_out - check_in).days, guests=guests,
            results=len(results), channel=channel,
        )
    )
    return results
