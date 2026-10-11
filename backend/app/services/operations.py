"""Operations layer: turns every booking into a run-sheet executed by verified local partners.

Partners (housekeepers, drivers, chefs, guides, security, technicians) are dispatched by skill,
distance, rating and current load. Work is proven with GPS check-in inside a geofence around
the unit plus photo evidence, then verified and rated — the same discipline a hotel's
housekeeping and engineering departments run, distributed across a city.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Booking, OpsTask, Partner, Property, TaskKind, TaskStatus, utcnow

GEOFENCE_METERS = 250

SKILL_FOR_TASK = {
    TaskKind.cleaning: "housekeeping",
    TaskKind.linen: "housekeeping",
    TaskKind.inspection: "inspection",
    TaskKind.security: "security",
    TaskKind.transfer: "driver",
    TaskKind.chef: "chef",
    TaskKind.concierge: "concierge",
    TaskKind.maintenance: "maintenance",
}

# Tasks performed away from the unit (e.g. airport pickups) skip the geofence.
OFFSITE_TASKS = {TaskKind.transfer, TaskKind.concierge}
PRE_ARRIVAL = {TaskKind.cleaning, TaskKind.linen, TaskKind.inspection}
OPEN_STATES = (TaskStatus.open, TaskStatus.assigned, TaskStatus.in_progress)


class OpsError(Exception):
    pass


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def create_task(
    db: Session,
    prop: Property,
    kind: TaskKind,
    title: str,
    due_at: datetime,
    *,
    booking: Booking | None = None,
    notes: str | None = None,
    auto_dispatch: bool = True,
) -> OpsTask:
    task = OpsTask(
        property_id=prop.id,
        booking_id=booking.id if booking else None,
        kind=kind,
        title=title,
        due_at=due_at,
        notes=notes,
        requires_photo=kind not in OFFSITE_TASKS,
    )
    db.add(task)
    db.flush()
    if auto_dispatch:
        dispatch(db, task)
    return task


def tasks_for_booking(db: Session, booking: Booking) -> list[OpsTask]:
    """The standard luxury run-sheet for one stay."""
    prop = booking.property
    eve = datetime.combine(booking.check_in - timedelta(days=1), time(10, 0))
    arrival = datetime.combine(booking.check_in, time(12, 0))
    departure = datetime.combine(booking.check_out, time(11, 30))
    plan = [
        (TaskKind.cleaning, f"Deep clean before arrival · {booking.code}", eve),
        (TaskKind.linen, f"Fresh linen & towels · {booking.code}", eve),
        (TaskKind.inspection, f"Pre-arrival inspection (power, water, Wi-Fi, safety) · {booking.code}", arrival),
        (TaskKind.cleaning, f"Turnover after departure · {booking.code}", departure),
    ]
    if booking.airport_transfer:
        plan.append((TaskKind.transfer, f"Airport pickup · {booking.code}", datetime.combine(booking.check_in, time(10, 0))))
    return [create_task(db, prop, kind, title, due, booking=booking) for kind, title, due in plan]


def _open_load(db: Session, partner_id: int) -> int:
    return db.scalar(
        select(func.count(OpsTask.id)).where(OpsTask.partner_id == partner_id, OpsTask.status.in_(OPEN_STATES))
    ) or 0


def rank_partners(db: Session, task: OpsTask) -> list[dict]:
    prop = task.property
    skill = SKILL_FOR_TASK[task.kind]
    partners = db.scalars(
        select(Partner).where(Partner.city == prop.city, Partner.active.is_(True), Partner.verified.is_(True))
    )
    ranked = []
    for p in partners:
        if skill not in (p.skills or []):
            continue
        dist_km = haversine_m(p.lat, p.lng, prop.lat, prop.lng) / 1000 if prop.lat is not None else 0.0
        load = _open_load(db, p.id)
        score = p.rating * 20 - dist_km * 1.5 - load * 5
        ranked.append({"partner": p, "distance_km": round(dist_km, 2), "load": load, "score": round(score, 2)})
    return sorted(ranked, key=lambda r: r["score"], reverse=True)


def dispatch(db: Session, task: OpsTask) -> Partner | None:
    if task.status not in (TaskStatus.open, TaskStatus.assigned):
        raise OpsError("Only open tasks can be dispatched")
    ranked = rank_partners(db, task)
    if not ranked:
        task.partner_id, task.status = None, TaskStatus.open
        return None
    task.partner_id = ranked[0]["partner"].id
    task.status = TaskStatus.assigned
    db.flush()
    return ranked[0]["partner"]


def check_in(db: Session, task: OpsTask, partner: Partner, lat: float, lng: float) -> OpsTask:
    if task.partner_id != partner.id:
        raise OpsError("Task is not assigned to you")
    if task.status != TaskStatus.assigned:
        raise OpsError(f"Cannot check in to a task that is {task.status.value}")
    prop = task.property
    distance = haversine_m(lat, lng, prop.lat, prop.lng) if prop.lat is not None else 0.0
    if task.kind not in OFFSITE_TASKS and distance > GEOFENCE_METERS:
        raise OpsError(f"Check-in is {distance:.0f} m from the unit; must be within {GEOFENCE_METERS} m")
    task.checkin_lat, task.checkin_lng, task.checkin_distance_m = lat, lng, round(distance, 1)
    task.started_at = utcnow()
    task.status = TaskStatus.in_progress
    return task


def complete(db: Session, task: OpsTask, partner: Partner, photos: list[str], notes: str | None) -> OpsTask:
    if task.partner_id != partner.id:
        raise OpsError("Task is not assigned to you")
    if task.status != TaskStatus.in_progress:
        raise OpsError("Check in before completing the task")
    if task.requires_photo and not photos:
        raise OpsError("Photo proof is required for this task")
    task.proof_photos = list(photos)
    task.notes = notes or task.notes
    task.completed_at = utcnow()
    task.status = TaskStatus.done
    partner.jobs_done += 1
    return task


def verify(db: Session, task: OpsTask, rating: int) -> OpsTask:
    if task.status != TaskStatus.done:
        raise OpsError("Only completed tasks can be verified")
    if not 1 <= rating <= 5:
        raise OpsError("Rating must be 1–5")
    task.status = TaskStatus.verified
    task.rating = rating
    if task.partner:
        p = task.partner
        # Bayesian-ish running mean: seed rating counts as 3 prior jobs so one rating can't swing it wildly.
        prior = 3
        p.rating = round((p.rating * (p.ratings_count + prior) + rating) / (p.ratings_count + prior + 1), 3)
        p.ratings_count += 1
    return task


def cancel_booking_tasks(db: Session, booking: Booking) -> None:
    for t in db.scalars(select(OpsTask).where(OpsTask.booking_id == booking.id, OpsTask.status.in_(OPEN_STATES))):
        t.status = TaskStatus.cancelled


def unit_ready(db: Session, booking: Booking) -> dict:
    tasks = list(
        db.scalars(select(OpsTask).where(OpsTask.booking_id == booking.id, OpsTask.kind.in_(PRE_ARRIVAL)))
    )
    pre = [t for t in tasks if t.due_at.date() <= booking.check_in]
    done = [t for t in pre if t.status in (TaskStatus.done, TaskStatus.verified)]
    return {"ready": bool(pre) and len(done) == len(pre), "completed": len(done), "total": len(pre)}
