"""Anonymised demand intelligence for developers, investors and tourism boards.

Aggregates search and booking activity per market/month: where demand is, what it pays, and
where it goes unmet (searches with no verified supply) — i.e. where the next flexible inventory
cluster should be activated. Cells backed by fewer than k bookings are suppressed so no
individual stay or owner can be re-identified.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Booking, BookingStatus, Property, SearchLog
from .markets import MARKETS

PAID = (BookingStatus.confirmed, BookingStatus.checked_in, BookingStatus.completed)


def market_insights(db: Session) -> dict:
    k = settings.insights_k_anonymity
    cells: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"searches": 0, "zero_result_searches": 0, "bookings": 0, "room_nights": 0, "revenue_cents": 0, "lead_days": []}
    )
    for s in db.scalars(select(SearchLog)):
        c = cells[(s.city, s.check_in.strftime("%Y-%m"))]
        c["searches"] += 1
        c["zero_result_searches"] += 1 if s.results == 0 else 0
    rows = db.execute(select(Booking, Property.city).join(Property).where(Booking.status.in_(PAID)))
    for b, city in rows:
        c = cells[(city, b.check_in.strftime("%Y-%m"))]
        c["bookings"] += 1
        c["room_nights"] += (b.check_out - b.check_in).days
        c["revenue_cents"] += b.accommodation_cents - b.discount_cents
        c["lead_days"].append((b.check_in - b.created_at.date()).days)

    out = []
    for (city, month), c in sorted(cells.items()):
        suppressed = c["bookings"] < k
        unmet = c["zero_result_searches"] / c["searches"] if c["searches"] else 0.0
        out.append(
            {
                "market": city,
                "market_name": MARKETS[city].name if city in MARKETS else city,
                "month": month,
                "searches": c["searches"],
                "unmet_demand_rate": round(unmet, 3),
                "bookings": None if suppressed else c["bookings"],
                "adr_cents": None if suppressed or not c["room_nights"] else c["revenue_cents"] // c["room_nights"],
                "avg_lead_days": None if suppressed else round(sum(c["lead_days"]) / len(c["lead_days"]), 1),
                "suppressed": suppressed,
            }
        )

    by_market: dict[str, dict] = defaultdict(lambda: {"searches": 0, "zero": 0})
    for (city, _), c in cells.items():
        by_market[city]["searches"] += c["searches"]
        by_market[city]["zero"] += c["zero_result_searches"]
    expansion = sorted(
        (
            {
                "market": city,
                "market_name": MARKETS[city].name if city in MARKETS else city,
                "searches": v["searches"],
                "unmet_searches": v["zero"],
                "unmet_demand_rate": round(v["zero"] / v["searches"], 3),
            }
            for city, v in by_market.items()
            if v["searches"]
        ),
        key=lambda r: (r["unmet_searches"], r["unmet_demand_rate"]),
        reverse=True,
    )
    return {"k_anonymity": k, "cells": out, "expansion_candidates": expansion}
