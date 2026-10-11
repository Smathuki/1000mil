import os

os.environ["MAKAO_DATABASE_URL"] = "sqlite://"
os.environ["MAKAO_SEED"] = "0"
os.environ["MAKAO_PAYMENTS_MODE"] = "sandbox"

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

GUEST = {"Authorization": "Bearer demo-guest"}
OWNER = {"Authorization": "Bearer demo-owner"}
ADMIN = {"Authorization": "Bearer demo-admin"}


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
        yield session


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c


def future(days: int) -> date:
    return date.today() + timedelta(days=days)


def prop_id(client, name: str) -> int:
    for p in client.get("/api/owner/properties", headers=ADMIN).json():
        if p["name"] == name:
            return p["id"]
    raise KeyError(name)


def free_window(client, pid: int, nights: int = 3, start_after: int = 40) -> tuple[str, str]:
    """First run of free nights for a property, far enough out to avoid seeded blocks/events."""
    cal = client.get(f"/api/properties/{pid}/availability", params={"start": str(future(start_after)), "days": 120}).json()
    run = []
    for d in cal:
        run = run + [d["date"]] if d["available"] else []
        if len(run) == nights + 1:
            return run[0], run[-1]
    raise AssertionError("no free window")
