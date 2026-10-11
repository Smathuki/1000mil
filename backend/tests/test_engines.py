"""Unit tests for the pricing, availability/iCal, readiness and quality engines."""

from datetime import date, timedelta

from sqlalchemy import select

from app.models import BlockSource, DemandSignal, Property
from app.services import availability, pricing, quality, readiness


def _prop(db, name):
    return db.scalar(select(Property).where(Property.name == name))


def test_season_and_event_factors(db):
    mara = _prop(db, "Olare Ridge Lodge")
    today = date(2027, 1, 1)
    peak = pricing.price_stay(db, mara, date(2027, 8, 10), date(2027, 8, 11), today=today, occupancy={})[0]
    rains = pricing.price_stay(db, mara, date(2027, 4, 20), date(2027, 4, 21), today=today, occupancy={})[0]
    assert peak.factors["season"] == 1.40 and rains.factors["season"] == 0.75
    assert peak.factors["events"] > 1 and "Great Migration river crossings" in peak.signals
    assert peak.price_cents > rains.price_cents


def test_compression_gap_fill_lead_time_and_clamp(db):
    p = _prop(db, "Westlands Sky Residence")
    today = date(2027, 3, 1)
    night = date(2027, 3, 3)
    full = pricing.price_stay(db, p, night, night + timedelta(days=1), today=today, occupancy={night: 1.0})[0]
    empty = pricing.price_stay(db, p, night, night + timedelta(days=1), today=today, occupancy={night: 0.0})[0]
    assert full.factors["compression"] == 1.3 and empty.factors["compression"] == 0.9
    assert full.factors["lead_time"] == 1.12
    db.add(DemandSignal(name="Mega event", city="nairobi", kind="conference", start=night, end=night + timedelta(days=1), intensity=1))
    db.add(DemandSignal(name="Another", city="nairobi", kind="conference", start=night, end=night + timedelta(days=1), intensity=1))
    db.flush()
    surge = pricing.price_stay(db, p, night, night + timedelta(days=1), today=today, occupancy={night: 1.0})[0]
    assert surge.factors["events"] == 1.6  # intensities cap at 1
    assert surge.factors["total"] <= pricing.CEILING


def test_long_stay_discount(db):
    p = _prop(db, "Kilimani Loft for Nomads")
    start = date(2027, 6, 1)
    month = pricing.price_stay(db, p, start, start + timedelta(days=30), today=date(2027, 1, 1), occupancy={})
    assert month[0].factors["length_of_stay"] == 0.75


def test_ical_roundtrip_and_conflicts(db):
    p = _prop(db, "Kigali Executive Suites")
    feed = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:abc@airbnb.com\r\nDTSTART;VALUE=DATE:20280105\r\n"
        "DTEND;VALUE=DATE:20280108\r\nSUMMARY:Reserved\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:def@airbnb.com\r\nDTSTART:20280210T140000Z\r\nDTEND:20280212T100000Z\r\n"
        "SUMMARY:Not avail\r\n able\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    events = availability.parse_ical(feed)
    assert [(e["start"], e["end"]) for e in events] == [(date(2028, 1, 5), date(2028, 1, 8)), (date(2028, 2, 10), date(2028, 2, 12))]
    assert events[1]["summary"] == "Not available"

    availability.add_block(db, p, date(2028, 1, 6), date(2028, 1, 7), BlockSource.booking)
    result = availability.sync_ical(db, p, BlockSource.airbnb, feed)
    assert result["imported"] == 2 and len(result["conflicts"]) == 1
    assert not availability.is_available(db, p.id, date(2028, 2, 11), date(2028, 2, 12))
    # Re-sync with an empty feed replaces channel blocks only.
    availability.sync_ical(db, p, BlockSource.airbnb, "BEGIN:VCALENDAR\r\nEND:VCALENDAR")
    assert availability.is_available(db, p.id, date(2028, 2, 10), date(2028, 2, 12))
    assert not availability.is_available(db, p.id, date(2028, 1, 6), date(2028, 1, 7))

    exported = availability.export_ical(db, p)
    assert "DTSTART;VALUE=DATE:20280106" in exported and "BEGIN:VCALENDAR" in exported


def test_readiness_scoring():
    bare = Property(name="x", power_backup="none", water_backup=False, security=[], staff=[], wifi_mbps=0, photos=[], amenities=[])
    full = Property(
        name="y", power_backup="hybrid", water_backup=True, security=["guard_24h", "cctv", "gated", "alarm"],
        staff=["housekeeper", "chef"], wifi_mbps=100, lat=1.0, lng=1.0, amenities=list(readiness.ESSENTIAL_AMENITIES),
        photos=[{"room": r, "verified": True} for r in readiness.ROOMS_TO_PHOTOGRAPH],
    )
    assert readiness.assess(bare)["score"] == 0
    assert readiness.assess(full)["score"] == 100
    assert all(c["hint"] for c in readiness.assess(bare)["checks"])


def test_review_aspects():
    a = quality.lexicon_aspects("The villa was spotless. But the wifi was terrible and slow! Staff were friendly.")
    assert a == {"cleanliness": 1, "connectivity": -1, "staff": 1}
    assert quality.lexicon_aspects("We arrived on Tuesday.") == {}


def test_weak_unit_is_delisted_and_strong_stays_active(db):
    weak = _prop(db, "Paje Kite Beach House")
    strong = _prop(db, "Karen Ivory Villa")
    assert weak.status.value == "suspended" and weak.quality_score < quality.DELIST_BELOW
    assert strong.status.value == "active" and strong.quality_score >= quality.COACHING_BELOW
    assert "accuracy" in quality.score_property(db, weak)["weak_aspects"]
