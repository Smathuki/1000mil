from datetime import date, timedelta

from .conftest import ADMIN, GUEST, prop_id


def _legs(client):
    nbo = prop_id(client, "Westlands Sky Residence")
    mara = prop_id(client, "Olare Ridge Lodge")
    znz = prop_id(client, "Stone Town Merchant's House")
    start = date.today() + timedelta(days=150)
    d = lambda n: (start + timedelta(days=n)).isoformat()  # noqa: E731
    return [
        {"property_id": nbo, "check_in": d(0), "check_out": d(2), "guests": 2, "airport_transfer": True},
        {"property_id": mara, "check_in": d(2), "check_out": d(5), "guests": 2},
        {"property_id": znz, "check_in": d(5), "check_out": d(9), "guests": 2},
    ]


def test_itinerary_quote_applies_package_discount(client):
    q = client.post("/api/quote/itinerary", json={"legs": _legs(client)}).json()
    assert q["discount_rate"] == 0.05
    assert q["discount_cents"] > 0
    assert q["all_available"] is True
    assert q["total_cents"] == sum(leg["total_cents"] for leg in q["legs"])


def test_package_booking_and_single_payment(client):
    pkg = client.post("/api/packages", headers=GUEST, json={"legs": _legs(client)})
    assert pkg.status_code == 201, pkg.text
    pkg = pkg.json()
    assert len(pkg["bookings"]) == 3
    # Transfers arranged between legs automatically.
    assert all(b["airport_transfer"] for b in pkg["bookings"])
    # Individual legs can't be paid separately.
    assert client.post("/api/payments", headers=GUEST,
                       json={"method": "card", "booking_id": pkg["bookings"][0]["id"], "card_token": "tok_success"}).status_code == 402
    pay = client.post("/api/payments", headers=GUEST, json={"method": "card", "package_id": pkg["id"], "card_token": "tok_success"}).json()
    assert pay["status"] == "succeeded"
    full = client.get(f"/api/packages/{pkg['code']}", headers=GUEST).json()
    assert full["status"] == "confirmed"
    assert {b["status"] for b in full["bookings"]} == {"confirmed"}


def test_package_is_all_or_nothing(client):
    legs = _legs(client)
    # Someone else takes the Mara leg first.
    taken = client.post("/api/bookings", headers=ADMIN, json={k: legs[1][k] for k in ("property_id", "check_in", "check_out", "guests")})
    assert taken.status_code == 201
    r = client.post("/api/packages", headers=GUEST, json={"legs": legs})
    assert r.status_code == 409
    # Nairobi leg must not have been left on hold.
    nbo = {k: legs[0][k] for k in ("property_id", "check_in", "check_out", "guests")}
    assert client.post("/api/bookings", headers=GUEST, json=nbo).status_code == 201


def test_overlapping_legs_rejected(client):
    legs = _legs(client)
    legs[1]["check_in"] = legs[0]["check_in"]
    assert client.post("/api/packages", headers=GUEST, json={"legs": legs}).status_code == 409
