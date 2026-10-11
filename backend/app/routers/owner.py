"""Owner console: listings, hotel-ready assessment, calendar control, channel sync, earnings."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import date, timedelta
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import owned_property, require
from ..models import (
    BlockSource,
    Booking,
    BookingStatus,
    CalendarBlock,
    ChannelFeed,
    EscrowStatus,
    Property,
    PropertyStatus,
    Role,
    User,
    utcnow,
)
from ..schemas import (
    BlockIn,
    BlockOut,
    FeedIn,
    IcalImportIn,
    OwnerBookingOut,
    OwnerProperty,
    PropertyIn,
    PropertyPatch,
)
from ..services import availability, iot, pricing, quality, readiness
from ..services.markets import get_market

router = APIRouter(prefix="/owner", tags=["owner"])
public = APIRouter(tags=["channels"])
owner_only = require(Role.owner)


def _slugify(name: str, city: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{name} {city}".lower()).strip("-")
    return f"{base}-{secrets.token_hex(2)}"


# External calendars are fetched server-side, so only well-known channel hosts are allowed.
FEED_HOSTS = ("airbnb.com", "airbnb.co.uk", "booking.com", "vrbo.com", "google.com")


def _allowed_feed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in FEED_HOSTS)


def ical_key(property_id: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"ical:{property_id}".encode(), hashlib.sha256).hexdigest()[:24]


def _refresh_readiness(prop: Property) -> dict:
    result = readiness.assess(prop)
    prop.readiness_score = result["score"]
    return result


@router.get("/properties", response_model=list[OwnerProperty])
def my_properties(user: User = Depends(owner_only), db: Session = Depends(get_db)):
    stmt = select(Property).order_by(Property.id)
    if user.role != Role.admin:
        stmt = stmt.where(Property.owner_id == user.id)
    return list(db.scalars(stmt))


@router.post("/properties", response_model=OwnerProperty, status_code=201)
def create_property(body: PropertyIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    data = body.model_dump()
    prop = Property(owner_id=user.id, slug=_slugify(body.name, body.city), country=get_market(body.city).country, **data)
    _refresh_readiness(prop)
    db.add(prop)
    db.commit()
    return prop


@router.patch("/properties/{property_id}", response_model=OwnerProperty)
def update_property(property_id: int, body: PropertyPatch, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(prop, key, value)
    _refresh_readiness(prop)
    db.commit()
    return prop


@router.get("/properties/{property_id}/readiness")
def get_readiness(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    result = _refresh_readiness(prop)
    db.commit()
    return {**result, "threshold": settings.min_readiness_to_activate, "status": prop.status.value}


@router.post("/properties/{property_id}/activate", response_model=OwnerProperty)
def activate(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    """Go live on the network once the unit is hotel-ready. Suspended units need an admin re-inspection."""
    prop = owned_property(property_id, db, user)
    if prop.status == PropertyStatus.suspended and user.role != Role.admin:
        raise HTTPException(409, "Suspended for quality — an inspection must clear the unit first")
    result = _refresh_readiness(prop)
    if result["score"] < settings.min_readiness_to_activate:
        missing = [c["label"] for c in result["checks"] if c["hint"]]
        raise HTTPException(409, f"Readiness {result['score']}/100 — needs {settings.min_readiness_to_activate}. Improve: {', '.join(missing)}")
    prop.status, prop.status_reason = PropertyStatus.active, None
    db.commit()
    return prop


@router.post("/properties/{property_id}/pause", response_model=OwnerProperty)
def pause(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    if prop.status != PropertyStatus.suspended:
        prop.status, prop.status_reason = PropertyStatus.draft, "Paused by owner"
    db.commit()
    return prop


@router.get("/properties/{property_id}/quality")
def get_quality(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    return quality.score_property(db, prop)


@router.get("/properties/{property_id}/calendar")
def owner_calendar(
    property_id: int, start: date | None = None, days: int = Query(60, ge=1, le=366),
    user: User = Depends(owner_only), db: Session = Depends(get_db),
):
    prop = owned_property(property_id, db, user)
    start = start or date.today()
    cal = availability.calendar(db, prop, start, days)
    prices = {n.date.isoformat(): n.price_cents for n in pricing.price_stay(db, prop, start, start + timedelta(days=days))}
    for d in cal:
        d["price_cents"] = prices.get(d["date"])
    return cal


@router.post("/properties/{property_id}/blocks", response_model=BlockOut, status_code=201)
def block_dates(property_id: int, body: BlockIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    block = availability.add_block(db, prop, body.start, body.end, BlockSource(body.source), note=body.note)
    db.commit()
    return block


@router.delete("/properties/{property_id}/blocks/{block_id}", status_code=204)
def unblock(property_id: int, block_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    block = db.get(CalendarBlock, block_id)
    if block is None or block.property_id != prop.id:
        raise HTTPException(404, "Block not found")
    if block.source not in (BlockSource.owner, BlockSource.maintenance, BlockSource.whatsapp):
        raise HTTPException(409, "Guest bookings and channel blocks can't be removed here")
    db.delete(block)
    db.commit()


@router.get("/properties/{property_id}/blocks", response_model=list[BlockOut])
def list_blocks(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    return list(db.scalars(select(CalendarBlock).where(CalendarBlock.property_id == prop.id).order_by(CalendarBlock.start)))


@router.post("/properties/{property_id}/ical/import")
def import_ical(property_id: int, body: IcalImportIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    result = availability.sync_ical(db, prop, BlockSource(body.channel), body.ical)
    db.commit()
    return result


@router.post("/properties/{property_id}/feeds", status_code=201)
def add_feed(property_id: int, body: FeedIn, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    if not _allowed_feed(body.ical_url):
        raise HTTPException(400, f"Feed must be an https URL on {', '.join(FEED_HOSTS)}")
    feed = ChannelFeed(property_id=prop.id, channel=BlockSource(body.channel), ical_url=body.ical_url)
    db.add(feed)
    db.commit()
    return {"id": feed.id, "channel": feed.channel.value, "ical_url": feed.ical_url}


@router.post("/properties/{property_id}/feeds/sync")
def sync_feeds(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    results = []
    for feed in prop.feeds:
        try:
            if not _allowed_feed(feed.ical_url):
                raise ValueError("feed host not allowed")
            resp = httpx.get(feed.ical_url, timeout=15, follow_redirects=False)
            resp.raise_for_status()
            outcome = availability.sync_ical(db, prop, feed.channel, resp.text)
            feed.last_result = f"ok: {outcome['imported']} events, {len(outcome['conflicts'])} conflicts"
        except (httpx.HTTPError, ValueError) as exc:
            outcome = {"error": str(exc)}
            feed.last_result = f"error: {exc}"[:255]
        feed.last_synced_at = utcnow()
        results.append({"channel": feed.channel.value, **outcome})
    db.commit()
    return results


@router.get("/properties/{property_id}/channels")
def channel_links(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    prop = owned_property(property_id, db, user)
    return {
        "export_url": f"/api/ical/{prop.id}.ics?key={ical_key(prop.id)}",
        "feeds": [{"id": f.id, "channel": f.channel.value, "ical_url": f.ical_url, "last_synced_at": f.last_synced_at,
                   "last_result": f.last_result} for f in prop.feeds],
    }


@router.post("/properties/{property_id}/device-key")
def rotate_device_key(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    """Issue a credential for the unit's IoT gateway. Shown once; only its hash is stored."""
    prop = owned_property(property_id, db, user)
    key = "dev_" + secrets.token_urlsafe(24)
    prop.device_key_hash = iot.hash_device_key(key)
    db.commit()
    return {"property_id": prop.id, "device_key": key}


@router.get("/properties/{property_id}/status")
def unit_status(property_id: int, user: User = Depends(owner_only), db: Session = Depends(get_db)):
    return iot.unit_status(db, owned_property(property_id, db, user))


@router.get("/bookings", response_model=list[OwnerBookingOut])
def owner_bookings(user: User = Depends(owner_only), db: Session = Depends(get_db)):
    stmt = select(Booking).join(Property).order_by(Booking.check_in)
    if user.role != Role.admin:
        stmt = stmt.where(Property.owner_id == user.id)
    return list(db.scalars(stmt.where(Booking.status != BookingStatus.expired)))


@router.get("/earnings")
def earnings(user: User = Depends(owner_only), db: Session = Depends(get_db)):
    stmt = select(Booking).join(Property).where(Property.owner_id == user.id)
    paid_states = (BookingStatus.confirmed, BookingStatus.checked_in, BookingStatus.completed, BookingStatus.cancelled)
    out = {"in_escrow_cents": 0, "paid_out_cents": 0, "commission_cents": 0, "bookings": 0, "room_nights": 0}
    for b in db.scalars(stmt.where(Booking.status.in_(paid_states))):
        if b.escrow == EscrowStatus.none:
            continue
        if b.escrow == EscrowStatus.held:
            out["in_escrow_cents"] += b.owner_payout_cents
        elif b.escrow in (EscrowStatus.released, EscrowStatus.partially_refunded):
            out["paid_out_cents"] += b.owner_payout_cents
        out["commission_cents"] += b.commission_cents
        if b.status != BookingStatus.cancelled:
            out["bookings"] += 1
            out["room_nights"] += (b.check_out - b.check_in).days
    out["full_service"] = user.full_service
    return out


@public.get("/ical/{property_id}.ics", response_class=PlainTextResponse)
def ical_export(property_id: int, key: str, db: Session = Depends(get_db)):
    if not hmac.compare_digest(key, ical_key(property_id)):
        raise HTTPException(404, "Not found")
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(404, "Not found")
    return PlainTextResponse(availability.export_ical(db, prop), media_type="text/calendar")
