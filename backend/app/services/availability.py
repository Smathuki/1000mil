"""Availability engine: one calendar per unit, fed by owners, bookings, holds and external channels.

Owners keep control: they block/unblock any time, and external channels (Airbnb, Booking.com,
direct WhatsApp deals) are mirrored in via iCal so the network only ever surfaces dates that are
genuinely free. We publish our own iCal feed so the same unit never double-books elsewhere.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from ..models import BlockSource, CalendarBlock, Property, utcnow


class Unavailable(Exception):
    pass


def _active_blocks_clause(now: datetime):
    # Holds stop blocking once they expire; everything else blocks until removed.
    return or_(CalendarBlock.expires_at.is_(None), CalendarBlock.expires_at > now)


def overlapping_blocks(db: Session, property_id: int, start: date, end: date) -> list[CalendarBlock]:
    now = utcnow()
    stmt = select(CalendarBlock).where(
        CalendarBlock.property_id == property_id,
        CalendarBlock.start < end,
        CalendarBlock.end > start,
        _active_blocks_clause(now),
    )
    return list(db.scalars(stmt))


def is_available(db: Session, property_id: int, start: date, end: date) -> bool:
    return not overlapping_blocks(db, property_id, start, end)


def unavailable_property_ids(db: Session, property_ids: list[int], start: date, end: date) -> set[int]:
    if not property_ids:
        return set()
    stmt = select(CalendarBlock.property_id).where(
        CalendarBlock.property_id.in_(property_ids),
        CalendarBlock.start < end,
        CalendarBlock.end > start,
        _active_blocks_clause(utcnow()),
    )
    return set(db.scalars(stmt))


def add_block(
    db: Session,
    prop: Property,
    start: date,
    end: date,
    source: BlockSource,
    *,
    booking_id: int | None = None,
    note: str | None = None,
    expires_at: datetime | None = None,
    external_uid: str | None = None,
    allow_overlap: bool = False,
) -> CalendarBlock:
    if end <= start:
        raise ValueError("Block end must be after start")
    if not allow_overlap and overlapping_blocks(db, prop.id, start, end):
        raise Unavailable(f"{prop.name} is not available {start} → {end}")
    block = CalendarBlock(
        property_id=prop.id,
        start=start,
        end=end,
        source=source,
        booking_id=booking_id,
        note=note,
        expires_at=expires_at,
        external_uid=external_uid,
    )
    db.add(block)
    db.flush()
    return block


def purge_expired_holds(db: Session) -> int:
    result = db.execute(
        delete(CalendarBlock).where(
            and_(CalendarBlock.source == BlockSource.hold, CalendarBlock.expires_at <= utcnow())
        )
    )
    return result.rowcount or 0


def calendar(db: Session, prop: Property, start: date, days: int) -> list[dict]:
    """Day-by-day view used by owner and guest calendars."""
    end = start + timedelta(days=days)
    blocks = overlapping_blocks(db, prop.id, start, end)
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        hit = next((b for b in blocks if b.start <= day < b.end), None)
        out.append(
            {
                "date": day.isoformat(),
                "available": hit is None,
                "source": hit.source.value if hit else None,
                "block_id": hit.id if hit else None,
            }
        )
    return out


# ---------------------------------------------------------------- iCal (RFC 5545 subset)

_LINE_UNFOLD = re.compile(r"\r?\n[ \t]")


def _parse_ical_date(value: str) -> date:
    digits = value.split("T", 1)[0][:8]
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))


def parse_ical(text: str) -> list[dict]:
    """Extract VEVENT date ranges. Handles DATE and DATE-TIME forms and folded lines."""
    text = _LINE_UNFOLD.sub("", text)
    events: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current and "start" in current:
                current.setdefault("end", current["start"] + timedelta(days=1))
                if current["end"] > current["start"]:
                    events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            name = key.split(";", 1)[0].upper()
            if name == "DTSTART":
                current["start"] = _parse_ical_date(value)
            elif name == "DTEND":
                current["end"] = _parse_ical_date(value)
            elif name == "UID":
                current["uid"] = value
            elif name == "SUMMARY":
                current["summary"] = value
    return events


def sync_ical(db: Session, prop: Property, channel: BlockSource, text: str) -> dict:
    """Replace all blocks from `channel` with the feed's current events.

    Channel blocks are mirrored even when they collide with our own bookings (the conflict is
    surfaced to ops rather than silently dropped), so we never under-report external occupancy.
    """
    events = parse_ical(text)
    db.execute(
        delete(CalendarBlock).where(CalendarBlock.property_id == prop.id, CalendarBlock.source == channel)
    )
    conflicts = []
    for ev in events:
        clash = [
            b
            for b in overlapping_blocks(db, prop.id, ev["start"], ev["end"])
            if b.source in (BlockSource.booking, BlockSource.hold)
        ]
        if clash:
            conflicts.append({"start": ev["start"].isoformat(), "end": ev["end"].isoformat()})
        add_block(
            db,
            prop,
            ev["start"],
            ev["end"],
            channel,
            note=ev.get("summary"),
            external_uid=ev.get("uid"),
            allow_overlap=True,
        )
    return {"imported": len(events), "conflicts": conflicts}


def export_ical(db: Session, prop: Property) -> str:
    """Feed for external channels: every date unavailable on Makao, except blocks they gave us."""
    stmt = select(CalendarBlock).where(
        CalendarBlock.property_id == prop.id,
        CalendarBlock.source.notin_([BlockSource.airbnb, BlockSource.booking_com]),
        _active_blocks_clause(utcnow()),
    )
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Makao//Flexible Luxury Network//EN",
        "CALSCALE:GREGORIAN",
    ]
    for b in db.scalars(stmt):
        lines += [
            "BEGIN:VEVENT",
            f"UID:makao-{prop.id}-{b.id}@makao.africa",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{b.start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{b.end.strftime('%Y%m%d')}",
            "SUMMARY:Unavailable (Makao)",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
