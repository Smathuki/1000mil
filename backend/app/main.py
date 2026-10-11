from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import Base, SessionLocal, engine
from .routers import bookings, catalog, messaging, ops, owner
from .services.availability import Unavailable
from .services.booking import BookingError
from .services.operations import OpsError
from .services.payments import PaymentError


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    if os.environ.get("MAKAO_SEED", "1") == "1":
        from .seed import seed_if_empty

        with SessionLocal() as db:
            seed_if_empty(db)
    yield


app = FastAPI(
    title="Makao — flexible luxury network",
    version="0.1.0",
    description="On-demand luxury inventory network for East Africa: inventory, availability, "
    "dynamic pricing, bookings & itineraries, payments, operations, smart-unit telemetry and quality.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error(status: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


app.add_exception_handler(Unavailable, _error(409))
app.add_exception_handler(BookingError, _error(409))
app.add_exception_handler(OpsError, _error(409))
app.add_exception_handler(PaymentError, _error(402))

for r in (catalog.router, bookings.router, owner.router, owner.public, ops.router, messaging.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True, "payments_mode": settings.payments_mode, "messaging_mode": settings.messaging_mode}
