"""WhatsApp-first booking concierge.

Guests in the region default to WhatsApp, so the network answers there: a free-text message like
"Villa in Nairobi 12-15 Dec for 4" is parsed into a search, and the reply carries live options,
prices and a one-tap booking link. Booking codes can be checked with "status MKXXXXXX".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Booking, MessageLog, PropertyKind, utcnow
from . import search as search_svc
from .markets import MARKETS

CITY_ALIASES = {
    "nairobi": "nairobi", "nbo": "nairobi", "karen": "nairobi", "westlands": "nairobi", "runda": "nairobi",
    "mara": "maasai-mara", "masai mara": "maasai-mara", "maasai mara": "maasai-mara",
    "diani": "diani", "ukunda": "diani",
    "zanzibar": "zanzibar", "znz": "zanzibar", "stone town": "zanzibar", "nungwi": "zanzibar", "paje": "zanzibar",
    "arusha": "arusha", "serengeti": "arusha", "ngorongoro": "arusha", "kilimanjaro": "arusha",
    "dar": "dar-es-salaam", "dar es salaam": "dar-es-salaam",
    "kigali": "kigali", "rwanda": "kigali",
    "kampala": "kampala", "entebbe": "kampala",
    "addis": "addis-ababa", "addis ababa": "addis-ababa",
}
KIND_WORDS = {"villa": PropertyKind.villa, "apartment": PropertyKind.apartment, "lodge": PropertyKind.lodge,
              "camp": PropertyKind.tented_camp, "house": PropertyKind.residence, "residence": PropertyKind.residence}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


@dataclass
class Intent:
    city: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    guests: int = 2
    kind: PropertyKind | None = None
    status_code: str | None = None


def _year_for(month: int, day: int, today: date) -> date:
    candidate = date(today.year, month, day)
    return candidate if candidate >= today else date(today.year + 1, month, day)


def parse(text: str, today: date) -> Intent:
    t = " " + text.lower().strip() + " "
    intent = Intent()

    m = re.search(r"\bstatus\s+((?:mk|pk)[a-z0-9]{6})\b", t)
    if m:
        intent.status_code = m.group(1).upper()
        return intent

    for alias in sorted(CITY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", t):
            intent.city = CITY_ALIASES[alias]
            break
    for word, kind in KIND_WORDS.items():
        if re.search(rf"\b{word}s?\b", t):
            intent.kind = kind
            break

    nights = None
    if m := re.search(r"(\d+)\s*nights?", t):
        nights = int(m.group(1))
        t = t.replace(m.group(0), " ")
    m = None

    mon = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    try:
        if m := re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|-|–|until)\s*(\d{4}-\d{2}-\d{2})", t):
            intent.check_in, intent.check_out = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
        elif m := re.search(rf"(\d{{1,2}})\s*{mon}\s*(?:to|-|–|until)\s*(\d{{1,2}})\s*{mon}", t):
            intent.check_in = _year_for(MONTHS[m.group(2)], int(m.group(1)), today)
            intent.check_out = _year_for(MONTHS[m.group(4)], int(m.group(3)), today)
        elif m := re.search(rf"(\d{{1,2}})\s*(?:-|–|to)\s*(\d{{1,2}})\s*{mon}", t):
            intent.check_in = _year_for(MONTHS[m.group(3)], int(m.group(1)), today)
            intent.check_out = _year_for(MONTHS[m.group(3)], int(m.group(2)), today)
        elif m := re.search(rf"(\d{{1,2}})\s*{mon}", t):
            intent.check_in = _year_for(MONTHS[m.group(2)], int(m.group(1)), today)
        elif "tonight" in t:
            intent.check_in = today
        elif "tomorrow" in t:
            intent.check_in = today + timedelta(days=1)
        elif "this weekend" in t or "weekend" in t:
            intent.check_in = today + timedelta(days=(4 - today.weekday()) % 7)
            nights = nights or 2
    except ValueError:
        intent.check_in = intent.check_out = None
    if m:
        t = t.replace(m.group(0), " ")  # so "12-15 dec" is not read as "for 12" guests

    m = re.search(r"(\d+)\s*(?:guests?|people|pax|adults|persons?|of us)\b", t) or re.search(r"\bfor\s+(\d{1,2})\b(?!\s*nights?)", t)
    if m:
        intent.guests = max(1, min(30, int(m.group(1))))

    if intent.check_in and intent.check_out and intent.check_out <= intent.check_in:
        intent.check_out = date(intent.check_out.year + 1, intent.check_out.month, intent.check_out.day)
    if intent.check_in and not intent.check_out:
        intent.check_out = intent.check_in + timedelta(days=nights or 2)
    return intent


def _usd(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def reply_for(db: Session, text: str, *, today: date | None = None) -> str:
    today = today or utcnow().date()
    intent = parse(text, today)

    if intent.status_code:
        b = db.scalar(select(Booking).where(Booking.code == intent.status_code))
        if not b:
            return f"I couldn't find booking {intent.status_code}. Check the code and try again."
        return (f"{b.code} · {b.property.name}\n{b.check_in:%d %b} → {b.check_out:%d %b} · {b.guests} guests\n"
                f"Status: {b.status.value.replace('_', ' ')}\nManage your stay: {settings.public_base_url}/stay/{b.code}")

    if not intent.city:
        cities = ", ".join(m.name for m in MARKETS.values())
        return ("Karibu to Makao 🌍 Tell me where and when, e.g. \"Villa in Nairobi 12-15 Dec for 4\".\n"
                f"We cover: {cities}.")
    if not intent.check_in:
        return f"Great — {MARKETS[intent.city].name}. Which dates? e.g. \"12-15 Dec\" or \"this weekend\"."

    results = search_svc.search(db, intent.city, intent.check_in, intent.check_out, intent.guests,
                                kind=intent.kind, channel="whatsapp", today=today)
    nights = (intent.check_out - intent.check_in).days
    header = f"{MARKETS[intent.city].name} · {intent.check_in:%d %b} → {intent.check_out:%d %b} ({nights} nights) · {intent.guests} guests"
    if not results:
        return header + "\nNothing verified is free for those dates yet — a concierge will message you with options within 30 minutes."
    lines = [header]
    for i, r in enumerate(results[:3], 1):
        p = r["property"]
        lines.append(f"{i}. {p.name} — {p.bedrooms} bd, sleeps {p.max_guests} · {_usd(r['nightly_avg_cents'])}/night "
                     f"({_usd(r['accommodation_cents'])} total)\n   {settings.public_base_url}/p/{p.slug}"
                     f"?in={intent.check_in}&out={intent.check_out}&guests={intent.guests}")
    if any(r["signals"] for r in results[:3]):
        lines.append("Heads-up: high demand (" + ", ".join(sorted({s for r in results[:3] for s in r['signals']})) + ").")
    lines.append("Pay with M-Pesa or card. Reply with a number for a concierge to hold it for you.")
    return "\n".join(lines)


def send(db: Session, channel: str, peer: str, body: str) -> None:
    db.add(MessageLog(channel=channel, direction="out", peer=peer, body=body))
    if settings.messaging_mode != "live" or channel != "whatsapp":
        return
    httpx.post(
        f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_id}/messages",
        headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        json={"messaging_product": "whatsapp", "to": peer, "type": "text", "text": {"body": body}},
        timeout=15,
    ).raise_for_status()


def handle_whatsapp_webhook(db: Session, payload: dict) -> list[dict]:
    """Meta Cloud API webhook: entry[].changes[].value.messages[] → replies."""
    handled = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") != "text":
                    continue
                peer, body = msg.get("from", ""), msg.get("text", {}).get("body", "")
                db.add(MessageLog(channel="whatsapp", direction="in", peer=peer, body=body))
                reply = reply_for(db, body)
                send(db, "whatsapp", peer, reply)
                handled.append({"from": peer, "reply": reply})
    return handled
