"""Smart-unit telemetry: power source, backup levels, water, security, door locks.

A small gateway in each unit (or the owner's existing solar/inverter controller) posts readings.
We turn them into a guest-facing status ("Running on solar, battery 82%"), proactive ops tasks
when something degrades, and uptime numbers that feed the quality score.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Booking,
    BookingStatus,
    OpsTask,
    Property,
    SensorReading,
    SupportTicket,
    TaskKind,
    utcnow,
)
from . import operations

METRICS = {"power_source", "battery_pct", "fuel_pct", "water_pct", "alarm", "door", "occupancy", "internet"}
POWER_SOURCES = {"grid", "solar", "generator", "battery", "outage"}


def hash_device_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _alerts(metric: str, value: str) -> list[tuple[TaskKind, str, str]]:
    """(task kind, title, priority) for readings that need someone on site."""
    out = []
    try:
        num = float(value)
    except ValueError:
        num = None
    if metric == "power_source" and value == "outage":
        out.append((TaskKind.maintenance, "Power outage — restore supply / start backup", "urgent"))
    elif metric == "fuel_pct" and num is not None and num < 15:
        out.append((TaskKind.maintenance, "Generator fuel below 15% — refuel", "high"))
    elif metric == "battery_pct" and num is not None and num < 20:
        out.append((TaskKind.maintenance, "Backup battery below 20% — check solar/inverter", "high"))
    elif metric == "water_pct" and num is not None and num < 20:
        out.append((TaskKind.maintenance, "Water tank below 20% — arrange refill", "high"))
    elif metric == "alarm" and value == "triggered":
        out.append((TaskKind.security, "Security alarm triggered — respond now", "urgent"))
    elif metric == "internet" and value == "down":
        out.append((TaskKind.maintenance, "Internet down — switch to backup link", "normal"))
    return out


def current_guest_booking(db: Session, prop: Property, now: datetime | None = None) -> Booking | None:
    today = (now or utcnow()).date()
    return db.scalar(
        select(Booking).where(
            Booking.property_id == prop.id,
            Booking.status.in_([BookingStatus.confirmed, BookingStatus.checked_in]),
            Booking.check_in <= today,
            Booking.check_out > today,
        )
    )


def ingest(db: Session, prop: Property, readings: list[dict]) -> dict:
    created_tasks = []
    stored = 0
    for r in readings:
        metric, value = r["metric"], str(r["value"])
        if metric not in METRICS:
            continue
        if metric == "power_source" and value not in POWER_SOURCES:
            continue
        db.add(SensorReading(property_id=prop.id, metric=metric, value=value, recorded_at=r.get("recorded_at") or utcnow()))
        stored += 1
        for kind, title, priority in _alerts(metric, value):
            duplicate = db.scalar(
                select(OpsTask).where(
                    OpsTask.property_id == prop.id, OpsTask.title == title, OpsTask.status.in_(operations.OPEN_STATES)
                )
            )
            if duplicate:
                continue
            task = operations.create_task(db, prop, kind, title, utcnow() + timedelta(hours=1), notes=f"Auto from {metric}={value}")
            created_tasks.append(task.id)
            stay = current_guest_booking(db, prop)
            if stay:
                db.add(SupportTicket(booking_id=stay.id, category="unit_alert", message=title, priority=priority))
    db.flush()
    return {"stored": stored, "tasks_created": created_tasks}


def latest(db: Session, prop: Property) -> dict[str, SensorReading]:
    out: dict[str, SensorReading] = {}
    rows = db.scalars(
        select(SensorReading)
        .where(SensorReading.property_id == prop.id)
        .order_by(SensorReading.recorded_at.desc())
        .limit(200)
    )
    for r in rows:
        out.setdefault(r.metric, r)
    return out


def power_uptime(db: Session, prop: Property, days: int = 30) -> float | None:
    since = utcnow() - timedelta(days=days)
    values = list(
        db.scalars(
            select(SensorReading.value).where(
                SensorReading.property_id == prop.id,
                SensorReading.metric == "power_source",
                SensorReading.recorded_at >= since,
            )
        )
    )
    if not values:
        return None
    return round(sum(1 for v in values if v != "outage") / len(values), 4)


def unit_status(db: Session, prop: Property) -> dict:
    last = latest(db, prop)

    def val(metric: str) -> str | None:
        return last[metric].value if metric in last else None

    source = val("power_source")
    power_label = {
        "grid": "Mains power",
        "solar": "Running on solar",
        "generator": "Running on generator",
        "battery": "Running on backup battery",
        "outage": "Power interrupted — team dispatched",
    }.get(source or "", "No live data")
    return {
        "power": {"source": source, "label": power_label, "battery_pct": val("battery_pct"), "fuel_pct": val("fuel_pct"),
                  "ok": source not in (None, "outage")},
        "water": {"tank_pct": val("water_pct"), "ok": val("water_pct") is None or float(val("water_pct")) >= 20},
        "security": {"alarm": val("alarm") or "unknown", "door": val("door") or "unknown",
                     "guard_on_site": "guard_24h" in (prop.security or []), "ok": val("alarm") != "triggered"},
        "internet": {"status": val("internet") or "unknown", "ok": val("internet") != "down"},
        "updated_at": max((r.recorded_at for r in last.values()), default=None),
        "uptime_30d": power_uptime(db, prop),
    }


def access_code(booking: Booking) -> str:
    digest = hmac.new(settings.secret_key.encode(), f"lock:{booking.code}".encode(), hashlib.sha256).hexdigest()
    return f"{int(digest[:12], 16) % 1_000_000:06d}"


def access_window(booking: Booking) -> tuple[datetime, datetime]:
    return datetime.combine(booking.check_in, time(14, 0)), datetime.combine(booking.check_out, time(11, 0))
