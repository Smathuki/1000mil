"""Demo data: a realistic launch network (Nairobi, safari gateways, coast, Kigali…).

Dates are generated relative to today so the demo always has upcoming demand signals, past stays
with reviews (for the quality board) and live telemetry. Demo bearer tokens are fixed strings for
local development only — production issues tokens through the auth/KYC flow.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .deps import hash_token
from .models import (
    BlockSource,
    Booking,
    BookingStatus,
    CalendarBlock,
    CancellationPolicy,
    DemandSignal,
    EscrowStatus,
    Partner,
    Property,
    PropertyKind,
    PropertyStatus,
    Review,
    Role,
    SearchLog,
    SensorReading,
    User,
    utcnow,
)
from .services import iot, quality, readiness
from .services.markets import MARKETS

DEMO_TOKENS = {
    "guest": "demo-guest",
    "owner": "demo-owner",
    "owner2": "demo-owner-2",
    "admin": "demo-admin",
    "partner": "demo-partner",
}
DEMO_DEVICE_KEY = "dev_demo_gateway_key"

FULL_KIT = ["hot_water", "linens", "towels", "kitchen", "air_conditioning_or_fans", "workspace", "pool", "garden", "parking"]
ROOMS = ["living", "bedroom", "bathroom", "kitchen", "exterior"]


def _photos(seed: str, n: int = 6) -> list[dict]:
    rooms = (ROOMS * 2)[:n]
    return [{"url": f"https://picsum.photos/seed/{seed}-{i}/1200/800", "room": r, "verified": True} for i, r in enumerate(rooms)]


PROPERTIES = [
    # (name, kind, city, neighbourhood, lat, lng, bd, ba, guests, rate $, cleaning $, min_n, power, security, staff, wifi, smart_lock, policy, description)
    ("Karen Ivory Villa", "villa", "nairobi", "Karen", -1.3197, 36.7073, 5, 5, 10, 520, 80, 2, "hybrid",
     ["guard_24h", "cctv", "gated", "alarm"], ["housekeeper", "chef"], 100, True, "moderate",
     "Five-suite colonial villa on two acres of indigenous garden, 10 minutes from the Giraffe Centre."),
    ("Westlands Sky Residence", "apartment", "nairobi", "Westlands", -1.2649, 36.8048, 3, 3, 6, 260, 40, 1, "generator",
     ["guard_24h", "cctv", "gated"], ["housekeeper"], 200, True, "flexible",
     "Penthouse with skyline terrace, walking distance to the business district and GTC."),
    ("Runda Diplomat House", "residence", "nairobi", "Runda", -1.2176, 36.8100, 4, 4, 8, 380, 60, 3, "solar",
     ["guard_24h", "gated", "cctv"], ["housekeeper", "driver"], 60, False, "moderate",
     "Quiet embassy-belt residence with staff quarters and a heated pool; ideal for delegations."),
    ("Kilimani Loft for Nomads", "apartment", "nairobi", "Kilimani", -1.2900, 36.7850, 1, 1, 2, 120, 20, 1, "inverter",
     ["guard_24h", "cctv"], ["housekeeper"], 150, True, "flexible",
     "Design-led loft with a dedicated workspace, fibre + 4G failover and a co-working pass."),
    ("Mara River Private Camp", "tented_camp", "maasai-mara", "Lemek Conservancy", -1.3500, 35.1500, 4, 4, 8, 900, 0, 2, "solar",
     ["guard_24h", "gated"], ["chef", "guide", "housekeeper"], 25, False, "strict",
     "Four exclusive-use tents above a migration crossing point, with private guide and vehicle."),
    ("Olare Ridge Lodge", "lodge", "maasai-mara", "Olare Motorogi", -1.3200, 35.2400, 3, 3, 6, 720, 0, 2, "hybrid",
     ["guard_24h"], ["chef", "guide"], 20, False, "strict",
     "Stone-and-thatch lodge on the conservancy ridge; sundowners overlooking the plains."),
    ("Diani Coral House", "villa", "diani", "Galu Beach", -4.3300, 39.5800, 4, 4, 8, 410, 60, 3, "generator",
     ["guard_24h", "gated"], ["housekeeper", "chef"], 40, False, "moderate",
     "Beachfront Swahili villa with makuti roof, infinity pool and direct reef access."),
    ("Nungwi Ocean Villa", "villa", "zanzibar", "Nungwi", -5.7269, 39.2961, 4, 4, 8, 480, 70, 3, "hybrid",
     ["guard_24h", "cctv", "gated"], ["housekeeper", "chef", "butler"], 60, True, "moderate",
     "Cliff-top villa on Zanzibar's northern tip; sunset dhows pass the terrace every evening."),
    ("Stone Town Merchant's House", "residence", "zanzibar", "Stone Town", -6.1622, 39.1880, 3, 3, 6, 290, 40, 2, "generator",
     ["guard_24h", "cctv"], ["housekeeper"], 30, False, "flexible",
     "Restored 19th-century merchant's house with carved doors and a rooftop over the old town."),
    ("Paje Kite Beach House", "residence", "zanzibar", "Paje", -6.2650, 39.5350, 3, 2, 6, 230, 40, 2, "inverter",
     ["gated"], ["housekeeper"], 30, False, "flexible",
     "Relaxed beach house on Paje lagoon; great for kitesurfers and longer stays."),
    ("Arusha Coffee Estate Manor", "residence", "arusha", "Usa River", -3.3700, 36.8500, 5, 5, 10, 450, 60, 2, "hybrid",
     ["guard_24h", "gated"], ["housekeeper", "chef", "driver"], 50, False, "moderate",
     "Manor on a working coffee estate below Mt Meru — the gateway night before Serengeti or Ngorongoro."),
    ("Kigali Hills Residence", "residence", "kigali", "Nyarutarama", -1.9380, 30.1030, 4, 4, 8, 340, 50, 2, "solar",
     ["guard_24h", "cctv", "gated"], ["housekeeper", "driver"], 150, True, "moderate",
     "Contemporary hillside residence 5 minutes from the Kigali Convention Centre."),
    ("Kigali Executive Suites", "apartment", "kigali", "Kiyovu", -1.9520, 30.0600, 2, 2, 4, 210, 30, 1, "generator",
     ["guard_24h", "cctv"], ["housekeeper"], 120, True, "flexible",
     "Serviced executive apartment with skyline views, for conference delegates and NGO leadership."),
    ("Entebbe Lakeside Villa", "villa", "kampala", "Entebbe", 0.0560, 32.4790, 4, 4, 8, 310, 50, 2, "generator",
     ["guard_24h", "gated"], ["housekeeper", "chef"], 40, False, "moderate",
     "Lake Victoria frontage, 10 minutes from EBB — the perfect landing after a long-haul flight."),
    ("Masaki Seafront Apartment", "apartment", "dar-es-salaam", "Masaki", -6.7470, 39.2780, 3, 3, 6, 240, 40, 1, "generator",
     ["guard_24h", "cctv", "gated"], ["housekeeper"], 80, True, "flexible",
     "Seafront apartment on the Msasani peninsula, close to embassies and Slipway."),
    ("Bole Atlas Penthouse", "apartment", "addis-ababa", "Bole", 8.9960, 38.7870, 3, 3, 6, 220, 30, 1, "inverter",
     ["guard_24h", "cctv"], ["housekeeper"], 50, False, "flexible",
     "Penthouse in Bole close to the AU and ECA — a calm base for summit weeks."),
]

PARTNERS = [
    ("Wanjiru Housekeeping Co.", ["housekeeping", "inspection"], "nairobi", -1.3000, 36.7800, 4.8),
    ("Otieno Swift Transfers", ["driver"], "nairobi", -1.3190, 36.9270, 4.7),
    ("Chef Akinyi Private Dining", ["chef", "concierge"], "nairobi", -1.2700, 36.8000, 4.9),
    ("Karen Tech & Power", ["maintenance"], "nairobi", -1.3300, 36.7100, 4.6),
    ("Simba Shield Security", ["security"], "nairobi", -1.2900, 36.8200, 4.5),
    ("Mara Camp Services", ["housekeeping", "inspection", "maintenance", "concierge"], "maasai-mara", -1.3400, 35.1800, 4.7),
    ("Mara Flying Doctors Transfers", ["driver"], "maasai-mara", -1.4061, 35.0089, 4.6),
    ("Diani Shores Hospitality", ["housekeeping", "inspection", "maintenance", "driver"], "diani", -4.3000, 39.5700, 4.6),
    ("Zanzibar Spice Concierge", ["concierge", "chef", "driver"], "zanzibar", -6.1600, 39.2000, 4.8),
    ("Nungwi Housekeeping Collective", ["housekeeping", "inspection"], "zanzibar", -5.7300, 39.2950, 4.7),
    ("Unguja Power & Water", ["maintenance"], "zanzibar", -6.1700, 39.2100, 4.4),
    ("Arusha Gateway Services", ["housekeeping", "inspection", "driver", "maintenance"], "arusha", -3.3800, 36.7000, 4.6),
    ("Kigali Premium Facilities", ["housekeeping", "inspection", "maintenance", "security"], "kigali", -1.9450, 30.0700, 4.8),
    ("Kigali Executive Chauffeurs", ["driver", "concierge"], "kigali", -1.9680, 30.1390, 4.9),
    ("Entebbe Home Services", ["housekeeping", "inspection", "driver", "maintenance"], "kampala", 0.0600, 32.4700, 4.5),
    ("Msasani Hospitality", ["housekeeping", "inspection", "driver", "maintenance"], "dar-es-salaam", -6.7500, 39.2700, 4.5),
    ("Bole Concierge & Care", ["housekeeping", "inspection", "driver", "maintenance"], "addis-ababa", 8.9900, 38.7800, 4.5),
]


def _signals(today: date) -> list[DemandSignal]:
    y = today.year
    out = []
    for year in (y, y + 1):
        out += [
            DemandSignal(name="Great Migration river crossings", city="maasai-mara", kind="safari",
                         start=date(year, 7, 15), end=date(year, 10, 15), intensity=0.6, source="seed:seasonal"),
            DemandSignal(name="Serengeti calving season", city="arusha", kind="safari",
                         start=date(year, 1, 15), end=date(year, 3, 1), intensity=0.4, source="seed:seasonal"),
            DemandSignal(name="Festive season & diaspora homecoming", city="nairobi", kind="diaspora",
                         start=date(year, 12, 18), end=date(year + 1, 1, 4), intensity=0.5, source="seed:seasonal"),
            DemandSignal(name="Festive season on the coast", city="diani", kind="holiday",
                         start=date(year, 12, 20), end=date(year + 1, 1, 3), intensity=0.7, source="seed:seasonal"),
            DemandSignal(name="Festive season in Zanzibar", city="zanzibar", kind="holiday",
                         start=date(year, 12, 20), end=date(year + 1, 1, 3), intensity=0.7, source="seed:seasonal"),
            DemandSignal(name="Sauti za Busara music festival", city="zanzibar", kind="sports",
                         start=date(year, 2, 12), end=date(year, 2, 16), intensity=0.5, source="seed:events"),
        ]
    # Rolling business events near "now" so the demo always shows event surges.
    out += [
        DemandSignal(name="Pan-African fintech summit (sample)", city="nairobi", kind="conference",
                     start=today + timedelta(days=12), end=today + timedelta(days=16), intensity=0.8, source="seed:events"),
        DemandSignal(name="Kigali convention week (sample)", city="kigali", kind="conference",
                     start=today + timedelta(days=20), end=today + timedelta(days=25), intensity=0.9, source="seed:events"),
        DemandSignal(name="AU ministerial session (sample)", city="addis-ababa", kind="conference",
                     start=today + timedelta(days=30), end=today + timedelta(days=34), intensity=0.7, source="seed:events"),
        DemandSignal(name="Long-haul arrivals surge — NBO (flight data)", city="nairobi", kind="flights",
                     start=today + timedelta(days=5), end=today + timedelta(days=9), intensity=0.3, source="seed:flights"),
    ]
    return out


REVIEW_SAMPLES = [
    (5, "Spotless house and incredibly friendly staff. Power never dropped, the solar backup was seamless."),
    (5, "Stunning views. The chef was exceptional and the airport pickup was on time."),
    (4, "Lovely, comfortable home. Wifi was a bit slow on the second day but the team fixed it fast."),
    (5, "Perfect base for our conference week. Safe, quiet and the driver was very helpful."),
]
MIXED_REVIEWS = [
    (4, "Beautiful old house and great location. Wifi was slow and unreliable for video calls."),
    (3, "Lovely staff but the generator was noisy and the hot water was cold in the mornings."),
    (4, "Charming rooftop. The photos were a bit misleading about the size of the bedrooms."),
]
WEAK_REVIEWS = [
    (2, "Photos were misleading. The bathroom was dirty and there was a damp smell."),
    (3, "Beautiful location but the generator was unreliable and we had a blackout two nights. Water pressure poor."),
    (2, "Wifi was terrible and the gate guard was rude."),
]


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count(User.id))):
        return
    seed(db)


def seed(db: Session) -> None:
    rnd = random.Random(42)
    today = utcnow().date()

    users = {
        "guest": User(name="Amina Diallo", email="guest@makao.demo", phone="0712345678", role=Role.guest,
                      token_hash=hash_token(DEMO_TOKENS["guest"]), kyc_verified=True),
        "owner": User(name="Joseph Kamau", email="owner@makao.demo", phone="0722000111", role=Role.owner,
                      token_hash=hash_token(DEMO_TOKENS["owner"]), kyc_verified=True, full_service=True),
        "owner2": User(name="Fatma Said", email="owner2@makao.demo", phone="+255777000222", role=Role.owner,
                       token_hash=hash_token(DEMO_TOKENS["owner2"]), kyc_verified=True),
        "admin": User(name="Makao Ops Desk", email="ops@makao.demo", role=Role.admin,
                      token_hash=hash_token(DEMO_TOKENS["admin"]), kyc_verified=True),
    }
    db.add_all(users.values())
    db.flush()

    for i, (name, skills, city, lat, lng, rating) in enumerate(PARTNERS):
        token = DEMO_TOKENS["partner"] if i == 0 else f"demo-partner-{i}"
        u = User(name=name, email=f"partner{i}@makao.demo", role=Role.partner, token_hash=hash_token(token), kyc_verified=True)
        db.add(u)
        db.flush()
        db.add(Partner(user_id=u.id, name=name, skills=skills, city=city, lat=lat, lng=lng, rating=rating,
                       ratings_count=rnd.randint(8, 60), jobs_done=rnd.randint(20, 300)))

    props = []
    for i, row in enumerate(PROPERTIES):
        (name, kind, city, hood, lat, lng, bd, ba, guests, rate, cleaning, min_n, power, security, staff, wifi,
         lock, policy, desc) = row
        owner = users["owner"] if MARKETS[city].country in ("KE", "RW", "UG", "ET") else users["owner2"]
        p = Property(
            owner_id=owner.id, name=name, slug=name.lower().replace("'", "").replace(" ", "-").replace("&", "and"),
            kind=PropertyKind(kind), city=city, country=MARKETS[city].country, neighbourhood=hood, lat=lat, lng=lng,
            description=desc, bedrooms=bd, bathrooms=ba, max_guests=guests, base_rate_cents=rate * 100,
            cleaning_fee_cents=cleaning * 100, min_nights=min_n, cancellation_policy=CancellationPolicy(policy),
            amenities=FULL_KIT, power_backup=power, water_backup=True, security=security, staff=staff,
            wifi_mbps=wifi, photos=_photos(f"makao{i}"), smart_lock=lock, status=PropertyStatus.active,
            device_key_hash=iot.hash_device_key(DEMO_DEVICE_KEY),
        )
        p.readiness_score = readiness.assess(p)["score"]
        db.add(p)
        props.append(p)
    # One onboarding-in-progress listing so the owner console shows the readiness flow.
    draft = Property(
        owner_id=users["owner"].id, name="Lavington Garden Cottage", slug="lavington-garden-cottage", kind=PropertyKind.residence,
        city="nairobi", country="KE", neighbourhood="Lavington", lat=-1.2780, lng=36.7690, description="Garden cottage being onboarded.",
        bedrooms=2, bathrooms=2, max_guests=4, base_rate_cents=15000, cleaning_fee_cents=3000, amenities=["linens", "towels", "kitchen"],
        power_backup="none", security=["gated"], staff=[], wifi_mbps=10, photos=_photos("lav", 2), status=PropertyStatus.draft,
    )
    draft.readiness_score = readiness.assess(draft)["score"]
    db.add(draft)
    db.add_all(_signals(today))
    db.flush()

    guest = users["guest"]
    weak = {p.id for p in props if p.name in ("Paje Kite Beach House",)}
    mixed = {p.id for p in props if p.name in ("Stone Town Merchant's House",)}
    for i, p in enumerate(props):
        # Past stays with reviews (feeds the quality board).
        if p.id in weak:
            samples = WEAK_REVIEWS
        elif p.id in mixed:
            samples = MIXED_REVIEWS
        else:
            samples = REVIEW_SAMPLES[i % 4:] + REVIEW_SAMPLES[: i % 4]
        for j, (rating, text) in enumerate(samples[:3]):
            start = today - timedelta(days=40 + j * 12 + rnd.randint(0, 5))
            end = start + timedelta(days=3)
            b = _past_booking(db, guest, p, start, end, rnd)
            db.add(Review(booking_id=b.id, property_id=p.id, rating=rating, text=text, aspects=quality.analyze_review(text)))
        # Some forward occupancy from other channels so compression pricing shows up.
        if rnd.random() < 0.5:
            s = today + timedelta(days=rnd.randint(3, 30))
            db.add(CalendarBlock(property_id=p.id, start=s, end=s + timedelta(days=rnd.randint(2, 5)),
                                 source=rnd.choice([BlockSource.airbnb, BlockSource.booking_com, BlockSource.owner]),
                                 note="Seeded external stay"))
        # Telemetry: mostly healthy, the weak unit has outages.
        for h in range(0, 72, 6):
            at = utcnow() - timedelta(hours=h)
            outage = p.id in weak and h % 24 == 0
            source = "outage" if outage else rnd.choice(["grid", "grid", "grid", "solar" if p.power_backup in ("solar", "hybrid") else "generator"])
            db.add(SensorReading(property_id=p.id, metric="power_source", value=source, recorded_at=at))
        db.add(SensorReading(property_id=p.id, metric="battery_pct", value=str(rnd.randint(55, 98))))
        db.add(SensorReading(property_id=p.id, metric="water_pct", value=str(rnd.randint(45, 95))))
        db.add(SensorReading(property_id=p.id, metric="alarm", value="armed"))
        db.add(SensorReading(property_id=p.id, metric="internet", value="up"))
    db.flush()
    for p in props:
        quality.apply_quality_actions(db, p)

    # Anonymous search history: Kampala/Addis/Arusha show unmet demand (expansion signal).
    for _ in range(160):
        city = rnd.choice(list(MARKETS))
        thin = city in ("kampala", "addis-ababa", "arusha")
        db.add(SearchLog(city=city, check_in=today + timedelta(days=rnd.randint(1, 90)), nights=rnd.randint(2, 7),
                         guests=rnd.randint(1, 8), results=0 if thin and rnd.random() < 0.6 else rnd.randint(1, 4),
                         channel=rnd.choice(["web", "whatsapp", "whatsapp"]),
                         created_at=utcnow() - timedelta(days=rnd.randint(0, 60))))
    db.commit()


def _past_booking(db: Session, guest: User, p: Property, start: date, end: date, rnd: random.Random) -> Booking:
    nights = (end - start).days
    nightly = p.base_rate_cents
    accommodation = nightly * nights
    service = accommodation * 5 // 100
    total = accommodation + p.cleaning_fee_cents + service
    commission = (accommodation + p.cleaning_fee_cents) * 18 // 100
    b = Booking(
        code="MKP" + "".join(rnd.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(5)),
        guest_id=guest.id, property_id=p.id, check_in=start, check_out=end, guests=2,
        nightly=[{"date": (start + timedelta(days=i)).isoformat(), "price_cents": nightly, "factors": {}, "signals": []}
                 for i in range(nights)],
        accommodation_cents=accommodation, cleaning_fee_cents=p.cleaning_fee_cents, service_fee_cents=service,
        total_cents=total, commission_cents=commission, owner_payout_cents=total - service - commission,
        cancellation_policy=p.cancellation_policy, status=BookingStatus.completed, escrow=EscrowStatus.released,
        created_at=datetime.combine(start - timedelta(days=rnd.randint(5, 40)), datetime.min.time()),
        confirmed_at=datetime.combine(start - timedelta(days=5), datetime.min.time()),
    )
    db.add(b)
    db.flush()
    db.add(CalendarBlock(property_id=p.id, start=start, end=end, source=BlockSource.booking, booking_id=b.id))
    return b


if __name__ == "__main__":  # python -m app.seed  (re-seed an empty database)
    from .db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_if_empty(session)
    print("Seeded. Demo tokens:", DEMO_TOKENS)
