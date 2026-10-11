"""Yield-oriented dynamic pricing.

nightly = base × season × weekend × events × compression × lead_time × length_of_stay,
clamped to [FLOOR, CEILING] × base so owners are protected from both runaway discounting and
price-gouging optics. Every night carries its factor breakdown so guests and owners can see *why*
a rate is what it is — transparency is part of the trust layer.

The model is deliberately interpretable. It is the baseline a learned model (e.g. gradient-boosted
demand forecasting on booking + search + flight data) is benchmarked against before replacing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CalendarBlock, DemandSignal, Property, PropertyStatus, utcnow
from .markets import get_market

FLOOR = 0.70
CEILING = 2.50
EVENT_MAX_UPLIFT = 0.60
COMPRESSION_START = 0.60
COMPRESSION_MAX_UPLIFT = 0.30
GAP_FILL_OCCUPANCY = 0.20
GAP_FILL_WINDOW_DAYS = 21
GAP_FILL_DISCOUNT = 0.90


@dataclass
class NightPrice:
    date: date
    price_cents: int
    factors: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "price_cents": self.price_cents,
            "factors": self.factors,
            "signals": self.signals,
        }


def _nights(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days)]


def market_occupancy(db: Session, city: str, start: date, end: date) -> dict[date, float]:
    """Share of the market's live units that are blocked on each night — our compression signal."""
    live = [PropertyStatus.active, PropertyStatus.coaching]
    ids = list(db.scalars(select(Property.id).where(Property.city == city, Property.status.in_(live))))
    if not ids:
        return {d: 0.0 for d in _nights(start, end)}
    now = utcnow()
    blocks = db.scalars(
        select(CalendarBlock).where(
            CalendarBlock.property_id.in_(ids),
            CalendarBlock.start < end,
            CalendarBlock.end > start,
            (CalendarBlock.expires_at.is_(None)) | (CalendarBlock.expires_at > now),
        )
    )
    taken: dict[date, set[int]] = {}
    for b in blocks:
        for d in _nights(max(b.start, start), min(b.end, end)):
            taken.setdefault(d, set()).add(b.property_id)
    return {d: len(taken.get(d, ())) / len(ids) for d in _nights(start, end)}


def _length_of_stay_factor(nights: int) -> float:
    if nights >= 28:
        return 0.75  # monthly stays for digital nomads / relocations
    if nights >= 7:
        return 0.90
    return 1.0


def _lead_time_factor(lead_days: int) -> float:
    if lead_days <= 2:
        return 1.12  # last-minute luxury: on-demand activation has real cost
    if lead_days <= 7:
        return 1.05
    return 1.0


def price_stay(
    db: Session,
    prop: Property,
    check_in: date,
    check_out: date,
    *,
    today: date | None = None,
    occupancy: dict[date, float] | None = None,
) -> list[NightPrice]:
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
    today = today or utcnow().date()
    market = get_market(prop.city)
    nights = _nights(check_in, check_out)
    occupancy = occupancy if occupancy is not None else market_occupancy(db, prop.city, check_in, check_out)
    signals = list(
        db.scalars(
            select(DemandSignal).where(
                DemandSignal.city == prop.city, DemandSignal.start < check_out, DemandSignal.end > check_in
            )
        )
    )
    los = _length_of_stay_factor(len(nights))
    lead = _lead_time_factor((check_in - today).days)

    out = []
    for night in nights:
        f: dict[str, float] = {}
        f["season"] = market.season_multiplier(night)
        f["weekend"] = 1 + market.weekend_uplift if night.weekday() in (4, 5) else 1.0

        active = [s for s in signals if s.start <= night < s.end]
        intensity = min(1.0, sum(s.intensity for s in active))
        f["events"] = round(1 + EVENT_MAX_UPLIFT * intensity, 4)

        occ = occupancy.get(night, 0.0)
        if occ > COMPRESSION_START:
            share = (occ - COMPRESSION_START) / (1 - COMPRESSION_START)
            f["compression"] = round(1 + COMPRESSION_MAX_UPLIFT * share, 4)
        elif occ < GAP_FILL_OCCUPANCY and (night - today).days <= GAP_FILL_WINDOW_DAYS:
            f["compression"] = GAP_FILL_DISCOUNT
        else:
            f["compression"] = 1.0

        f["lead_time"] = lead
        f["length_of_stay"] = los

        multiplier = 1.0
        for v in f.values():
            multiplier *= v
        multiplier = max(FLOOR, min(CEILING, multiplier))
        f["total"] = round(multiplier, 4)
        out.append(
            NightPrice(
                date=night,
                price_cents=int(round(prop.base_rate_cents * multiplier / 100.0)) * 100,  # whole dollars
                factors=f,
                signals=[s.name for s in active],
            )
        )
    return out


def demand_outlook(db: Session, city: str, start: date, days: int) -> list[dict]:
    """Market-level forward view for owners and the ops desk: occupancy, events, season."""
    end = start + timedelta(days=days)
    occ = market_occupancy(db, city, start, end)
    market = get_market(city)
    signals = list(
        db.scalars(select(DemandSignal).where(DemandSignal.city == city, DemandSignal.start < end, DemandSignal.end > start))
    )
    out = []
    for d in _nights(start, end):
        active = [s for s in signals if s.start <= d < s.end]
        out.append(
            {
                "date": d.isoformat(),
                "occupancy": round(occ[d], 3),
                "season": market.season_multiplier(d),
                "events": [s.name for s in active],
                "demand_index": round(
                    market.season_multiplier(d) * (1 + min(1.0, sum(s.intensity for s in active))) * (0.7 + occ[d]), 3
                ),
            }
        )
    return out

