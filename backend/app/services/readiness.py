"""The "hotel-ready" assessment from structured capture.

East African premium stock varies most on exactly the things that make or break a luxury stay:
power continuity, water, security, connectivity and staff. Each is captured as structured data at
onboarding (and later verified by an inspection partner + photo analysis), then scored.
A unit must reach `settings.min_readiness_to_activate` before it is surfaced to guests.
"""

from __future__ import annotations

from ..models import Property

ESSENTIAL_AMENITIES = {"hot_water", "linens", "towels", "kitchen", "air_conditioning_or_fans", "workspace"}
ROOMS_TO_PHOTOGRAPH = {"living", "bedroom", "bathroom", "kitchen", "exterior"}


def assess(prop: Property) -> dict:
    checks: list[dict] = []

    def check(key: str, label: str, weight: int, ok: float, hint: str) -> None:
        ok = max(0.0, min(1.0, ok))
        checks.append({"key": key, "label": label, "weight": weight, "score": round(weight * ok, 1), "hint": hint if ok < 1 else None})

    power = {"hybrid": 1.0, "solar": 0.9, "generator": 0.8, "inverter": 0.5}.get(prop.power_backup, 0.0)
    check("power", "Power continuity", 20, power, "Add generator/solar backup with automatic changeover.")
    check("water", "Water backup", 10, 1.0 if prop.water_backup else 0.0, "Install a storage tank with pump.")

    sec = set(prop.security or [])
    sec_score = (0.5 if "guard_24h" in sec else 0) + (0.2 if "cctv" in sec else 0) + (0.2 if "gated" in sec else 0)
    sec_score += 0.1 if ({"alarm", "safe"} & sec) else 0
    check("security", "Security", 15, sec_score, "24h guard + CCTV + gated access expected for luxury tier.")

    check("wifi", "Connectivity", 10, min(1.0, (prop.wifi_mbps or 0) / 25), "Fibre ≥25 Mbps with backup (4G/Starlink).")

    rooms = {p.get("room") for p in (prop.photos or [])}
    verified = sum(1 for p in (prop.photos or []) if p.get("verified"))
    photo_ok = 0.6 * (len(rooms & ROOMS_TO_PHOTOGRAPH) / len(ROOMS_TO_PHOTOGRAPH)) + 0.4 * min(1.0, verified / 5)
    check("photos", "Verified photography", 15, photo_ok, "Book a partner shoot: every room, ≥5 verified photos.")

    check("location", "Exact location", 5, 1.0 if prop.lat is not None and prop.lng is not None else 0.0, "Drop a GPS pin.")

    staff = set(prop.staff or [])
    check("staff", "On-site staff", 10, min(1.0, len(staff) / 2), "Housekeeper on-site; chef/butler on call.")

    amen = set(prop.amenities or [])
    check(
        "amenities",
        "Essential amenities",
        15,
        len(amen & ESSENTIAL_AMENITIES) / len(ESSENTIAL_AMENITIES),
        "Missing: " + ", ".join(sorted(ESSENTIAL_AMENITIES - amen)),
    )

    total = round(sum(c["score"] for c in checks))
    return {"score": total, "checks": checks}
