# Makao architecture

## Shape of the system

```
 Guests (web/PWA, WhatsApp) ─┐                         ┌─ Owners (console, iCal channels)
                              ▼                         ▼
                      ┌──────────────── FastAPI /api ────────────────┐
                      │ catalog · bookings · payments · guest app     │
                      │ owner · ops/admin · iot · messaging webhooks  │
                      └───────────────┬───────────────────────────────┘
                                      │  services (pure domain logic)
   availability ─ pricing ─ booking ─ payments ─ operations ─ iot ─ quality ─ readiness ─ insights
                                      │
                               SQLAlchemy models  (SQLite dev / Postgres prod)
                                      ▲
 Partners (job app: GPS + photo) ─────┘◄── IoT gateways (X-Device-Key telemetry)
```

Routers stay thin: they handle auth, input validation and the commit. All business rules live in `app/services/*` and are unit-testable without HTTP. Domain errors (`BookingError`, `Unavailable`, `OpsError`, `PaymentError`) are mapped to 409/402 in `main.py`. An uncommitted session is rolled back on close, which makes multi-step operations such as itineraries atomic.

## Data model (core)

- **Property**: structured capture (power backup, water, security, staff, Wi-Fi, verified photos, amenities), base rate, policy, `readiness_score`, `quality_score`, and `status` (draft → active ↔ coaching → suspended).
- **CalendarBlock** `[start, end)`, `source` ∈ owner | booking | hold | airbnb | booking_com | whatsapp | maintenance. Holds carry `expires_at`. This one table is the single source of availability truth.
- **Booking**: nightly price snapshot (with factor breakdown), fees, commission, owner payout, refund, `status`, `escrow`. A **Package** groups bookings into one itinerary.
- **Payment**: method, USD amount and local amount, provider reference (M-Pesa `CheckoutRequestID`), receipt.
- **Partner / OpsTask**: skills and geolocation; task lifecycle open → assigned → in_progress → done → verified, with GPS distance, photos and rating.
- **SensorReading, Review** (with extracted aspects), **SupportTicket, Upsell, DemandSignal, SearchLog, MessageLog**.

## Lifecycles

**Booking.** A quote leads to a create. Dates are held for 20 min (`hold` block) and the booking sits in `pending_payment`. On payment success (card or M-Pesa callback) the hold becomes a `booking` block, escrow is `held`, and the run-sheet tasks are created and dispatched. Then: guest check-in → escrow `released` 24h later (scheduled job) → `completed` after checkout. On cancellation, the refund follows the policy, blocks are deleted and open tasks are cancelled. Owner payout and commission are pro-rated to the retained amount. If payment arrives after the hold lapsed, the dates are re-taken if still free; otherwise the payment is marked refunded and the booking is never double-sold.

**Itinerary.** Legs are validated so they don't overlap, and each leg is held. Any failure rolls back the whole package. One payment confirms every leg; if any leg cannot be secured, all legs are refunded. Three or more legs earn a 5% discount. Inter-leg transfers are auto-added.

**Unit activation.** An owner creates a draft. The readiness score updates as data is captured; go-live requires ≥70. Quality is re-scored after each review: <70 → coaching (the owner gets a plan); <50 with ≥3 reviews → suspended until the ops desk reinstates the unit after inspection.

## Pricing model

`nightly = base × season × weekend × events × compression × lead_time × length_of_stay`, clamped to `[0.7, 2.5] × base`.

| Factor | Source |
|---|---|
| season | per-market monthly curves (safari / coast / business profiles) |
| weekend | Fri/Sat uplift in leisure markets |
| events | Σ intensity of overlapping `DemandSignal`s (capped at 1) → up to +60% |
| compression | live market occupancy: >60% → up to +30%; <20% within 21 days → −10% gap fill |
| lead_time | ≤2 days +12%, ≤7 days +5% (the cost of on-demand activation) |
| length_of_stay | ≥7 nights −10%, ≥28 nights −25% (nomads, relocations) |

Every night stores its factors, so guests see "why this price" and owners see the yield logic. The model is deliberately interpretable. It is the baseline a learned demand model must beat.

## Integrations

| Integration | Status | Where |
|---|---|---|
| M-Pesa Daraja STK push + callback | live-capable; sandbox simulates the exact callback payload | `services/payments.py` |
| Card acquiring | sandbox (`tok_success`); provider slot | `services/payments.py` |
| WhatsApp Cloud API webhook + send | live-capable; sandbox logs to `message_logs` | `services/messaging.py`, `routers/messaging.py` |
| Airbnb / Booking.com | iCal import (allow-listed hosts) + signed iCal export | `services/availability.py`, `routers/owner.py` |
| IoT gateways | per-unit device key (hashed), REST telemetry | `services/iot.py` |
| Smart locks | HMAC-derived 6-digit code bound to the stay window; vendor API slot | `services/iot.py` |
| Review analysis | lexicon aspect model behind the `ReviewAnalyzer` protocol, so an LLM analyser can drop in | `services/quality.py` |

## Security notes

- Bearer tokens are stored as SHA-256 hashes. Demo tokens are for local use only; production adds OTP login and KYC.
- Owners can only touch their own properties. Partners only see their own tasks. Guests only see their own stays, and other people's bookings return 404.
- iCal exports are signed per property (HMAC). Feed imports only fetch https URLs on allow-listed channel hosts, without following redirects, to prevent SSRF.
- The M-Pesa callback is idempotent, validates the amount, and always returns 200 to Daraja. Production should also restrict the callback to Safaricom IP ranges.
- Device keys are compared in constant time.
- Insights suppress cells with fewer than k bookings.

## Production roadmap

1. Postgres + Alembic migrations. Run the scheduled jobs (`/ops/jobs/run`) as cron or a worker. Add an exclusion constraint on `calendar_blocks` for hard double-booking protection under concurrency.
2. Auth: phone OTP, KYC provider for owners and high-value guests, plus RBAC for the ops desk.
3. Payments: card acquirer, MTN MoMo / Airtel Money / Telebirr adapters, automated owner payouts (B2C), multi-currency settlement.
4. Demand: flight schedule and arrivals feeds, conference calendars, tour-operator APIs. Train a demand forecaster on search + booking + signal history.
5. Ops: native partner app with camera capture and offline queue; SLA timers and escalation; route batching for housekeepers.
6. Trust: insurance partner integration, damage deposits, dispute workflow.
7. Data product: investor-facing dashboards on top of the k-anonymous insights.
