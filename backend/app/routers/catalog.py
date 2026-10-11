"""Public discovery: markets, search, listings, quotes, availability."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Property, PropertyKind
from ..schemas import PackageIn, PropertyDetail, QuoteIn, SearchResult
from ..services import availability, booking, pricing, search
from ..services.concierge import RECOMMENDATIONS
from ..services.markets import MARKETS

router = APIRouter(tags=["catalog"])


@router.get("/markets")
def markets(db: Session = Depends(get_db)):
    live: dict[str, int] = {}
    for city in db.scalars(select(Property.city).where(Property.status.in_(booking.BOOKABLE))):
        live[city] = live.get(city, 0) + 1
    return [
        {
            "key": m.key, "name": m.name, "country": m.country, "currency": m.currency,
            "airport": m.airport, "lat": m.lat, "lng": m.lng, "profile": m.profile, "live_units": live.get(m.key, 0),
        }
        for m in MARKETS.values()
    ]


@router.get("/markets/{city}/outlook")
def outlook(city: str, start: date | None = None, days: int = Query(30, ge=1, le=120), db: Session = Depends(get_db)):
    if city not in MARKETS:
        raise HTTPException(404, "Unknown market")
    return pricing.demand_outlook(db, city, start or date.today(), days)


@router.get("/search", response_model=list[SearchResult])
def do_search(
    city: str,
    check_in: date,
    check_out: date,
    guests: int = Query(2, ge=1, le=60),
    kind: PropertyKind | None = None,
    max_nightly: int | None = Query(None, description="USD per night"),
    db: Session = Depends(get_db),
):
    if city not in MARKETS:
        raise HTTPException(404, "Unknown market")
    if check_out <= check_in:
        raise HTTPException(400, "check_out must be after check_in")
    results = search.search(
        db, city, check_in, check_out, guests, kind=kind,
        max_nightly_cents=max_nightly * 100 if max_nightly else None,
    )
    db.commit()  # persist the anonymous search log
    return results


@router.get("/properties/{slug}", response_model=PropertyDetail)
def property_detail(slug: str, db: Session = Depends(get_db)):
    prop = db.scalar(select(Property).where(Property.slug == slug))
    if prop is None or prop.status not in booking.BOOKABLE:
        raise HTTPException(404, "Property not found")
    return prop


@router.get("/properties/{slug}/extras")
def property_extras(slug: str, db: Session = Depends(get_db)):
    prop = db.scalar(select(Property).where(Property.slug == slug))
    if prop is None:
        raise HTTPException(404, "Property not found")
    return {"recommendations": RECOMMENDATIONS.get(prop.city, []), "market": MARKETS[prop.city].name}


@router.get("/properties/{property_id}/availability")
def property_availability(
    property_id: int, start: date | None = None, days: int = Query(60, ge=1, le=366), db: Session = Depends(get_db)
):
    prop = db.get(Property, property_id)
    if prop is None or prop.status not in booking.BOOKABLE:
        raise HTTPException(404, "Property not found")
    # Guests only see free/busy, never why a date is blocked.
    return [{"date": d["date"], "available": d["available"]} for d in availability.calendar(db, prop, start or date.today(), days)]


@router.post("/quote")
def get_quote(body: QuoteIn, db: Session = Depends(get_db)):
    prop = db.get(Property, body.property_id)
    if prop is None:
        raise HTTPException(404, "Property not found")
    q = booking.quote(db, prop, body.check_in, body.check_out, body.guests)
    q.pop("commission_cents")
    q.pop("owner_payout_cents")
    return q


@router.post("/quote/itinerary")
def itinerary_quote(body: PackageIn, db: Session = Depends(get_db)):
    legs = booking.validate_itinerary([leg.model_dump() for leg in body.legs])
    rate = booking.package_discount_rate(len(legs))
    quotes = []
    for leg in legs:
        prop = db.get(Property, leg["property_id"])
        if prop is None:
            raise HTTPException(404, f"Property {leg['property_id']} not found")
        q = booking.quote(db, prop, leg["check_in"], leg["check_out"], leg["guests"], discount_rate=rate)
        q.pop("commission_cents")
        q.pop("owner_payout_cents")
        quotes.append(q)
    return {
        "legs": quotes,
        "discount_rate": rate,
        "discount_cents": sum(q["discount_cents"] for q in quotes),
        "total_cents": sum(q["total_cents"] for q in quotes),
        "all_available": all(q["available"] for q in quotes),
    }
