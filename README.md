# Makao — flexible luxury supply for East Africa

Makao is an on-demand luxury inventory network. It matches high-end demand (business travellers, safari guests, digital nomads, events, diaspora) with underused premium villas, apartments, lodges and private homes. It does this without the capital cost or rigidity of building new hotels.

The bottleneck is not demand or real estate. It is **coordination, trust and operations**. This repository is a working MVP of the platform that handles all three.

| Pillar | What is built |
|---|---|
| **1. Inventory aggregation & activation** | Owner onboarding. A structured "hotel-ready" assessment (power continuity, water, security, connectivity, staff, verified photos, amenities) that gates go-live. An owner-controlled availability calendar with instant block/unblock. Two-way channel sync via iCal (import Airbnb / Booking.com, export a signed feed back). |
| **2. Demand matching & dynamic pricing** | Interpretable yield engine: season × weekend × demand signals (conferences, migration, diaspora, flight surges) × market compression × short-notice premium × length-of-stay discount, clamped to a floor and ceiling. Instant booking with payment holds. Multi-property itineraries (e.g. Nairobi → Mara → Zanzibar) priced, held and paid as one package, all-or-nothing. A WhatsApp concierge that turns free text into live options. |
| **3. Operations layer** | Every booking generates a run-sheet (deep clean, linen, pre-arrival inspection, turnover, airport pickup). Tasks are auto-dispatched to verified local partners by skill, distance, rating and load. Work is proven by GPS geofenced check-in plus photo proof, then verified and rated. Smart-unit telemetry (power source, battery, fuel, water, alarm, internet) raises ops tasks and guest alerts automatically. The guest app shows live unit status, smart-lock codes, one-tap support and upsells. A quality engine (reviews + aspect mining + sensor uptime + incidents) coaches weak units or delists them. |
| **Trust & money** | M-Pesa STK push (Safaricom Daraja) and card payments. Escrow is released to the owner 24h after check-in, and refunds follow each unit's cancellation policy. Commission is 18%, plus 10% for owners on the full-service ops plan. Anonymised, k-suppressed demand insights show where to activate supply next. |

## Run it

**Backend** (Python 3.11+):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000/docs
pytest                                  # 35 tests
```

**Frontend** (Node 20+), in another terminal:

```bash
cd frontend
npm install
npm run dev                             # http://localhost:5173 (proxies /api → :8000)
```

**Or with Docker:** `docker compose up --build`, then open http://localhost:8080.

An empty database is seeded on first boot with 16 units across 9 markets, 17 partners, demand signals, past stays with reviews, and telemetry.

### Demo accounts

Use the **"Demo as"** switcher in the header. Each account is a bearer token, for local use only.

| Role | Token | Try this |
|---|---|---|
| Guest | `demo-guest` | Search → property → *Reserve & pay* → M-Pesa → *Approve on phone* → stay app. Build an itinerary. |
| Owner | `demo-owner` | Calendar with dynamic rates; block/release dates. Take *Lavington Garden Cottage* through readiness. iCal channels. Quality coaching. |
| Ops desk | `demo-admin` | Task board, support tickets, quality board (one unit is suspended, one is in coaching), demand signals, investor insights. |
| Partner | `demo-partner` | Wanjiru Housekeeping: check in on site (GPS or *Demo: I'm at the unit*), add photo proof, complete. |

The **Concierge** button runs the same parser and reply logic as the WhatsApp webhook. Try *"Villa in Zanzibar 28 dec - 3 jan for 6"* or *"status MKXXXXXX"*.

IoT gateways post readings with the demo device key:

```bash
curl -X POST localhost:8000/api/iot/1/telemetry -H 'X-Device-Key: dev_demo_gateway_key' \
  -H 'Content-Type: application/json' -d '{"readings":[{"metric":"power_source","value":"outage"}]}'
# → a maintenance task is created and dispatched; an in-house guest gets an alert
```

## Repository layout

```
backend/                FastAPI + SQLAlchemy (SQLite by default; Postgres-ready)
  app/services/         domain logic: availability, pricing, booking, payments, operations,
                        iot, quality, readiness, messaging, search, insights, markets, fees
  app/routers/          HTTP API: catalog, bookings (+ guest app, payments), owner, ops (+ admin, iot), messaging
  app/seed.py           demo network
  tests/                end-to-end API tests + engine unit tests
frontend/               React + Vite + TypeScript PWA (offline-capable service worker)
docs/ARCHITECTURE.md    design, data model, lifecycles, production roadmap
```

## What's real vs. sandboxed

- **Real logic:** availability with expiring holds, iCal parse/export, pricing, quotes and fees, packages, cancellation and refunds, escrow, dispatch ranking, geofencing, telemetry alerting, quality scoring and delisting, WhatsApp parsing, k-anonymous insights.
- **Real integrations, sandbox by default:** M-Pesa Daraja STK push and callback (set `MAKAO_PAYMENTS_MODE=live` and the Daraja credentials), and WhatsApp Cloud API send and webhook (`MAKAO_MESSAGING_MODE=live`). In sandbox mode the M-Pesa callback is simulated with Daraja's exact payload, so the production code path runs.
- **Provider slots, not yet wired:** card acquiring (Flutterwave / DPO / Stripe), KYC, a smart-lock vendor API, photo computer vision, an FX rates feed, and live flight and event feeds. Each sits behind a small interface; see `docs/ARCHITECTURE.md`.

See `backend/.env.example` for all configuration.
