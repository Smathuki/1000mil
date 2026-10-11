from sqlalchemy import select

from app.models import OpsTask, Partner, Property
from app.seed import DEMO_DEVICE_KEY
from app.services import messaging

from .conftest import ADMIN, GUEST, OWNER, free_window, future, prop_id

PARTNER = {"Authorization": "Bearer demo-partner"}  # Wanjiru Housekeeping, Nairobi


def _confirmed_booking(client, name="Karen Ivory Villa"):
    pid = prop_id(client, name)
    ci, co = free_window(client, pid)
    b = client.post("/api/bookings", headers=GUEST, json={"property_id": pid, "check_in": ci, "check_out": co, "guests": 2}).json()
    client.post("/api/payments", headers=GUEST, json={"method": "card", "booking_id": b["id"], "card_token": "tok_success"})
    return b


def test_partner_geofenced_checkin_photo_proof_and_rating(client, db):
    _confirmed_booking(client)
    tasks = client.get("/api/ops/tasks", headers=PARTNER, params={"status": "assigned"}).json()
    clean = next(t for t in tasks if t["kind"] == "cleaning")
    prop = db.get(Property, clean["property_id"])

    far = client.post(f"/api/ops/tasks/{clean['id']}/check-in", headers=PARTNER, json={"lat": -1.2864, "lng": 36.8172})
    assert far.status_code == 409 and "within" in far.json()["detail"]
    near = client.post(f"/api/ops/tasks/{clean['id']}/check-in", headers=PARTNER, json={"lat": prop.lat + 0.0005, "lng": prop.lng})
    assert near.status_code == 200 and near.json()["status"] == "in_progress"

    no_photo = client.post(f"/api/ops/tasks/{clean['id']}/complete", headers=PARTNER, json={"photos": []})
    assert no_photo.status_code == 409
    ok = client.post(f"/api/ops/tasks/{clean['id']}/complete", headers=PARTNER, json={"photos": ["https://cdn/x.jpg"]})
    assert ok.json()["status"] == "done"

    partner = db.scalar(select(Partner).where(Partner.name == "Wanjiru Housekeeping Co."))
    before = partner.rating
    v = client.post(f"/api/ops/tasks/{clean['id']}/verify", headers=ADMIN, json={"rating": 3})
    assert v.json()["status"] == "verified"
    db.expire_all()
    assert partner.rating < before


def test_partners_only_see_their_tasks(client):
    _confirmed_booking(client, "Nungwi Ocean Villa")  # Zanzibar: not Wanjiru's city
    assert all(t["property_id"] != prop_id(client, "Nungwi Ocean Villa") for t in client.get("/api/ops/tasks", headers=PARTNER).json())
    assert client.get("/api/ops/tasks", headers=GUEST).status_code == 403


def test_dispatch_ranking_prefers_skill_and_proximity(client):
    _confirmed_booking(client)
    task = client.get("/api/ops/tasks", headers=ADMIN, params={"city": "nairobi"}).json()
    transfer = next(t for t in task if t["kind"] == "inspection")
    ranked = client.get(f"/api/ops/tasks/{transfer['id']}/candidates", headers=ADMIN).json()
    assert ranked and ranked[0]["name"] == "Wanjiru Housekeeping Co."


def test_telemetry_outage_autodispatches_and_requires_device_key(client, db):
    pid = prop_id(client, "Karen Ivory Villa")
    body = {"readings": [{"metric": "power_source", "value": "outage"}, {"metric": "water_pct", "value": 12}]}
    assert client.post(f"/api/iot/{pid}/telemetry", json=body, headers={"X-Device-Key": "wrong"}).status_code == 401
    r = client.post(f"/api/iot/{pid}/telemetry", json=body, headers={"X-Device-Key": DEMO_DEVICE_KEY}).json()
    assert r["stored"] == 2 and len(r["tasks_created"]) == 2
    # Same alert again doesn't duplicate work.
    r2 = client.post(f"/api/iot/{pid}/telemetry", json=body, headers={"X-Device-Key": DEMO_DEVICE_KEY}).json()
    assert r2["tasks_created"] == []
    status = client.get(f"/api/owner/properties/{pid}/status", headers=OWNER).json()
    assert status["power"]["ok"] is False and status["water"]["ok"] is False
    assert db.scalar(select(OpsTask).where(OpsTask.id == r["tasks_created"][0])).partner_id is not None


def test_owner_onboarding_readiness_gate(client):
    r = client.post("/api/owner/properties", headers=OWNER, json={
        "name": "Muthaiga Garden Villa", "kind": "villa", "city": "nairobi", "bedrooms": 4, "bathrooms": 4,
        "max_guests": 8, "base_rate_cents": 40000, "power_backup": "none",
    })
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["status"] == "draft"
    blocked = client.post(f"/api/owner/properties/{pid}/activate", headers=OWNER)
    assert blocked.status_code == 409 and "Readiness" in blocked.json()["detail"]

    client.patch(f"/api/owner/properties/{pid}", headers=OWNER, json={
        "power_backup": "hybrid", "water_backup": True, "security": ["guard_24h", "cctv", "gated"],
        "staff": ["housekeeper", "chef"], "wifi_mbps": 50, "lat": -1.25, "lng": 36.83,
        "amenities": ["hot_water", "linens", "towels", "kitchen", "air_conditioning_or_fans", "workspace"],
        "photos": [{"url": f"https://x/{r}.jpg", "room": r, "verified": True} for r in ["living", "bedroom", "bathroom", "kitchen", "exterior"]],
    })
    ok = client.post(f"/api/owner/properties/{pid}/activate", headers=OWNER)
    assert ok.status_code == 200 and ok.json()["status"] == "active"
    # Other owners can't touch it.
    assert client.patch(f"/api/owner/properties/{pid}", headers={"Authorization": "Bearer demo-owner-2"}, json={"name": "Mine"}).status_code == 403


def test_owner_blocks_and_ical_export(client):
    pid = prop_id(client, "Karen Ivory Villa")
    s, e = str(future(200)), str(future(203))
    blk = client.post(f"/api/owner/properties/{pid}/blocks", headers=OWNER, json={"start": s, "end": e, "note": "Family visit"})
    assert blk.status_code == 201
    cal = client.get(f"/api/properties/{pid}/availability", params={"start": s, "days": 3}).json()
    assert not any(d["available"] for d in cal) and "source" not in cal[0]
    links = client.get(f"/api/owner/properties/{pid}/channels", headers=OWNER).json()
    ics = client.get(links["export_url"])
    assert ics.status_code == 200 and future(200).strftime("%Y%m%d") in ics.text
    assert client.get(f"/api/ical/{pid}.ics", params={"key": "nope"}).status_code == 404
    assert client.delete(f"/api/owner/properties/{pid}/blocks/{blk.json()['id']}", headers=OWNER).status_code == 204


def test_feed_host_allowlist(client):
    pid = prop_id(client, "Karen Ivory Villa")
    bad = client.post(f"/api/owner/properties/{pid}/feeds", headers=OWNER, json={"channel": "airbnb", "ical_url": "https://169.254.169.254/latest"})
    assert bad.status_code == 400
    good = client.post(f"/api/owner/properties/{pid}/feeds", headers=OWNER,
                       json={"channel": "airbnb", "ical_url": "https://www.airbnb.com/calendar/ical/123.ics?s=abc"})
    assert good.status_code == 201


def test_owner_earnings_reflect_escrow(client):
    _confirmed_booking(client)
    e = client.get("/api/owner/earnings", headers=OWNER).json()
    assert e["in_escrow_cents"] > 0 and e["paid_out_cents"] > 0 and e["full_service"] is True


def test_whatsapp_parsing():
    from datetime import date

    today = date(2026, 10, 11)
    i = messaging.parse("Hi! Need a villa in Nairobi 12-15 Dec for 4 please", today)
    assert (i.city, i.kind, i.check_in, i.check_out, i.guests) == ("nairobi", messaging.PropertyKind.villa, date(2026, 12, 12), date(2026, 12, 15), 4)
    i = messaging.parse("zanzibar 28 dec - 3 jan 6 guests", today)
    assert (i.check_in, i.check_out, i.guests) == (date(2026, 12, 28), date(2027, 1, 3), 6)
    i = messaging.parse("Mara lodge 2027-08-01 to 2027-08-04", today)
    assert (i.city, i.kind, i.check_in) == ("maasai-mara", messaging.PropertyKind.lodge, date(2027, 8, 1))
    i = messaging.parse("Kigali tonight for 3 nights", today)
    assert (i.check_in, i.check_out) == (today, date(2026, 10, 14))
    assert messaging.parse("status mkabc234", today).status_code == "MKABC234"


def test_whatsapp_webhook_and_chat(client):
    assert client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "makao-verify", "hub.challenge": "42"}).text == "42"
    assert client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"}).status_code == 403
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "254712345678", "type": "text",
                                                                "text": {"body": "Apartment in Kigali for 2, 3 nights from tomorrow"}}]}}]}]}
    assert client.post("/api/webhooks/whatsapp", json=payload).json() == {"handled": 1}
    log = client.get("/api/admin/messages", headers=ADMIN).json()
    assert log[0]["direction"] == "out" and "Kigali" in log[0]["body"]
    reply = client.post("/api/messaging/chat", json={"message": "hello"}).json()["reply"]
    assert "Karibu" in reply


def test_insights_k_anonymity(client):
    data = client.get("/api/admin/insights", headers=ADMIN).json()
    assert data["k_anonymity"] == 3
    assert data["expansion_candidates"][0]["market"] in ("kampala", "addis-ababa", "arusha")
    for cell in data["cells"]:
        if cell["suppressed"]:
            assert cell["bookings"] is None and cell["adr_cents"] is None
    assert client.get("/api/admin/insights", headers=OWNER).status_code == 403


def test_run_jobs(client):
    r = client.post("/api/ops/jobs/run", headers=ADMIN).json()
    assert set(r) == {"expired_bookings", "escrow_released", "completed_stays"}
