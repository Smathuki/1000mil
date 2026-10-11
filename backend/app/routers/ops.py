"""Ops desk and partner app: dispatch, GPS check-in, photo proof, verification, telemetry, quality."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, partner_for, require
from ..models import (
    Booking,
    BookingStatus,
    DemandSignal,
    MessageLog,
    OpsTask,
    Partner,
    Property,
    PropertyStatus,
    Role,
    SupportTicket,
    TaskStatus,
    User,
)
from ..schemas import (
    CheckInIn,
    CompleteIn,
    PartnerOut,
    SignalIn,
    TaskIn,
    TaskOut,
    TelemetryIn,
    UserOut,
    VerifyIn,
)
from ..services import booking as booking_svc
from ..services import insights, iot, operations, quality

router = APIRouter(tags=["ops"])
admin_only = require(Role.admin)
partner_or_admin = require(Role.partner)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


# ------------------------------------------------------------------ tasks


@router.get("/ops/tasks", response_model=list[TaskOut])
def list_tasks(
    status: TaskStatus | None = None, city: str | None = None,
    user: User = Depends(partner_or_admin), db: Session = Depends(get_db),
):
    stmt = select(OpsTask).join(Property).order_by(OpsTask.due_at)
    if user.role == Role.partner:
        stmt = stmt.where(OpsTask.partner_id == partner_for(user, db).id)
    if status:
        stmt = stmt.where(OpsTask.status == status)
    if city:
        stmt = stmt.where(Property.city == city)
    return list(db.scalars(stmt.limit(500)))


@router.post("/ops/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    prop = db.get(Property, body.property_id)
    if prop is None:
        raise HTTPException(404, "Property not found")
    task = operations.create_task(db, prop, body.kind, body.title, body.due_at, notes=body.notes)
    db.commit()
    return task


def _task(db: Session, task_id: int) -> OpsTask:
    task = db.get(OpsTask, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


@router.get("/ops/tasks/{task_id}/candidates")
def candidates(task_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [
        {"partner_id": r["partner"].id, "name": r["partner"].name, "rating": r["partner"].rating,
         "distance_km": r["distance_km"], "open_tasks": r["load"], "score": r["score"]}
        for r in operations.rank_partners(db, _task(db, task_id))
    ]


@router.post("/ops/tasks/{task_id}/dispatch", response_model=TaskOut)
def dispatch(task_id: int, partner_id: int | None = None, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    task = _task(db, task_id)
    if partner_id is not None:
        partner = db.get(Partner, partner_id)
        if partner is None or operations.SKILL_FOR_TASK[task.kind] not in partner.skills:
            raise HTTPException(400, "Partner lacks the skill for this task")
        if task.status not in (TaskStatus.open, TaskStatus.assigned):
            raise HTTPException(409, "Only open tasks can be reassigned")
        task.partner_id, task.status = partner.id, TaskStatus.assigned
    else:
        operations.dispatch(db, task)
    db.commit()
    return task


@router.post("/ops/tasks/{task_id}/check-in", response_model=TaskOut)
def task_check_in(task_id: int, body: CheckInIn, user: User = Depends(require(Role.partner)), db: Session = Depends(get_db)):
    task = operations.check_in(db, _task(db, task_id), partner_for(user, db), body.lat, body.lng)
    db.commit()
    return task


@router.post("/ops/tasks/{task_id}/complete", response_model=TaskOut)
def task_complete(task_id: int, body: CompleteIn, user: User = Depends(require(Role.partner)), db: Session = Depends(get_db)):
    task = operations.complete(db, _task(db, task_id), partner_for(user, db), body.photos, body.notes)
    db.commit()
    return task


@router.post("/ops/tasks/{task_id}/verify", response_model=TaskOut)
def task_verify(task_id: int, body: VerifyIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    task = operations.verify(db, _task(db, task_id), body.rating)
    db.commit()
    return task


@router.get("/ops/partners", response_model=list[PartnerOut])
def partners(city: str | None = None, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(Partner).order_by(Partner.city, Partner.rating.desc())
    if city:
        stmt = stmt.where(Partner.city == city)
    return list(db.scalars(stmt))


@router.get("/ops/tickets")
def tickets(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.execute(
        select(SupportTicket, Booking.code, Property.name)
        .join(Booking, SupportTicket.booking_id == Booking.id)
        .join(Property, Booking.property_id == Property.id)
        .order_by(SupportTicket.id.desc())
        .limit(200)
    )
    return [
        {"id": t.id, "booking": code, "property": name, "category": t.category, "message": t.message,
         "priority": t.priority, "status": t.status, "created_at": t.created_at}
        for t, code, name in rows
    ]


@router.post("/ops/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    t = db.get(SupportTicket, ticket_id)
    if t is None:
        raise HTTPException(404, "Ticket not found")
    t.status = "resolved"
    db.commit()
    return {"id": t.id, "status": t.status}


@router.post("/ops/jobs/run")
def run_jobs(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Periodic housekeeping (cron in production): expire unpaid holds, release due escrow, close stays."""
    expired = booking_svc.expire_unpaid(db)
    released = booking_svc.release_due_escrow(db)
    today = booking_svc.utcnow().date()
    completed = 0
    for b in db.scalars(select(Booking).where(Booking.status == BookingStatus.checked_in, Booking.check_out <= today)):
        b.status = BookingStatus.completed
        completed += 1
    db.commit()
    return {"expired_bookings": expired, "escrow_released": [b.code for b in released], "completed_stays": completed}


# ------------------------------------------------------------------ IoT


@router.post("/iot/{property_id}/telemetry")
def telemetry(property_id: int, body: TelemetryIn, x_device_key: str = Header(...), db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if prop is None or not prop.device_key_hash or not hmac.compare_digest(prop.device_key_hash, iot.hash_device_key(x_device_key)):
        raise HTTPException(401, "Unknown device")
    result = iot.ingest(db, prop, [r.model_dump() for r in body.readings])
    db.commit()
    return result


# ------------------------------------------------------------------ admin: quality, demand signals, insights


@router.get("/admin/quality")
def quality_board(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    out = []
    for p in db.scalars(select(Property).where(Property.status != PropertyStatus.draft).order_by(Property.city)):
        q = quality.score_property(db, p)
        out.append({"property_id": p.id, "name": p.name, "city": p.city, "status": p.status.value,
                    "status_reason": p.status_reason, "readiness": p.readiness_score, **q})
    return sorted(out, key=lambda r: (r["score"] is None, r["score"] or 0))


@router.post("/admin/properties/{property_id}/rescore")
def rescore(property_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(404, "Property not found")
    result = quality.apply_quality_actions(db, prop)
    db.commit()
    return result


@router.post("/admin/properties/{property_id}/reinstate")
def reinstate(property_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(404, "Property not found")
    prop.status, prop.status_reason = PropertyStatus.coaching, "Reinstated after inspection — on coaching plan"
    db.commit()
    return {"property_id": prop.id, "status": prop.status.value}


@router.get("/signals")
def list_signals(city: str | None = None, db: Session = Depends(get_db)):
    stmt = select(DemandSignal).order_by(DemandSignal.start)
    if city:
        stmt = stmt.where(DemandSignal.city == city)
    return [
        {"id": s.id, "name": s.name, "city": s.city, "kind": s.kind, "start": s.start, "end": s.end,
         "intensity": s.intensity, "source": s.source}
        for s in db.scalars(stmt)
    ]


@router.post("/signals", status_code=201)
def add_signal(body: SignalIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    if body.end <= body.start:
        raise HTTPException(400, "end must be after start")
    s = DemandSignal(**body.model_dump())
    db.add(s)
    db.commit()
    return {"id": s.id}


@router.get("/admin/insights")
def market_insights(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return insights.market_insights(db)


@router.get("/admin/messages")
def message_log(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [
        {"id": m.id, "channel": m.channel, "direction": m.direction, "peer": m.peer, "body": m.body, "at": m.created_at}
        for m in db.scalars(select(MessageLog).order_by(MessageLog.id.desc()).limit(100))
    ]
