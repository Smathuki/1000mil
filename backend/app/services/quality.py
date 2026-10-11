"""Post-stay quality control: reviews + ops evidence + sensor data → a unit quality score.

Review text is mined for aspect-level sentiment (cleanliness, power, water, security, staff,
connectivity, accuracy) with an interpretable lexicon model. It is a deliberate baseline: the
`ReviewAnalyzer` protocol lets an LLM-based analyser drop in without touching the scoring.

Scores drive actions automatically: ≥70 active, 50–70 coaching (owner gets a plan), <50 with
enough evidence → temporary delisting until an inspection clears it.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import OpsTask, Property, PropertyStatus, Review, TaskKind, utcnow
from . import iot

ASPECTS: dict[str, list[str]] = {
    "cleanliness": ["clean", "spotless", "dirty", "dust", "stain", "smell", "tidy", "mould", "mold"],
    "power": ["power", "electricity", "blackout", "outage", "generator", "solar", "lights"],
    "water": ["water", "shower", "pressure", "hot water", "tank"],
    "security": ["security", "safe", "guard", "gate", "unsafe", "lock"],
    "staff": ["staff", "host", "chef", "housekeeper", "butler", "driver", "guide", "service"],
    "connectivity": ["wifi", "wi-fi", "internet", "connection", "signal"],
    "accuracy": ["photos", "pictures", "as described", "listing", "expected"],
}
POSITIVE = {"great", "excellent", "amazing", "spotless", "clean", "fast", "friendly", "safe", "reliable", "perfect",
            "beautiful", "stunning", "lovely", "helpful", "seamless", "quiet", "comfortable", "exceptional"}
NEGATIVE = {"dirty", "slow", "broken", "unsafe", "rude", "noisy", "outage", "blackout", "cold", "smell", "stain",
            "mould", "mold", "poor", "terrible", "disappointing", "misleading", "late", "dust", "unreliable"}

COACHING_BELOW = 70
DELIST_BELOW = 50
MIN_REVIEWS_TO_DELIST = 3
COACHING_TIPS = {
    "cleanliness": "Schedule a partner deep-clean and add a housekeeping photo checklist.",
    "power": "Service backup power; enable solar/generator telemetry so outages auto-dispatch.",
    "water": "Install or enlarge the storage tank and add a level sensor.",
    "security": "Upgrade to 24h guard + CCTV; verify smart-lock coverage.",
    "staff": "Enrol on-site staff in Makao hospitality training.",
    "connectivity": "Add a backup link (4G router or Starlink) and test ≥25 Mbps.",
    "accuracy": "Re-shoot listing photos with a verified partner photographer.",
}


class ReviewAnalyzer(Protocol):
    def __call__(self, text: str) -> dict[str, int]: ...


def lexicon_aspects(text: str) -> dict[str, int]:
    """Sentence-level: an aspect mentioned in a sentence inherits that sentence's polarity."""
    out: dict[str, int] = {}
    for sentence in re.split(r"[.!?\n]+", text.lower()):
        words = set(re.findall(r"[a-z\-]+", sentence))
        polarity = len(words & POSITIVE) - len(words & NEGATIVE)
        if polarity == 0:
            continue
        sign = 1 if polarity > 0 else -1
        for aspect, cues in ASPECTS.items():
            if any(cue in sentence for cue in cues):
                out[aspect] = out.get(aspect, 0) + sign
    return {k: (1 if v > 0 else -1) for k, v in out.items() if v != 0}


analyze_review: ReviewAnalyzer = lexicon_aspects


def score_property(db: Session, prop: Property) -> dict:
    reviews = list(db.scalars(select(Review).where(Review.property_id == prop.id)))
    if not reviews:
        return {"score": None, "reviews": 0, "components": {}, "weak_aspects": []}

    rating = sum(r.rating for r in reviews) / len(reviews)
    aspect_totals: dict[str, int] = {}
    for r in reviews:
        for a, v in (r.aspects or {}).items():
            aspect_totals[a] = aspect_totals.get(a, 0) + v
    negatives = sorted([a for a, v in aspect_totals.items() if v < 0], key=lambda a: aspect_totals[a])
    aspect_score = max(0.0, 100 - 15 * sum(-v for v in aspect_totals.values() if v < 0))

    uptime = iot.power_uptime(db, prop, days=90)
    uptime_score = 100 * uptime if uptime is not None else 90.0  # no telemetry: neutral, slightly below perfect

    since = utcnow() - timedelta(days=90)
    incidents = db.scalar(
        select(func.count(OpsTask.id)).where(
            OpsTask.property_id == prop.id,
            OpsTask.kind.in_([TaskKind.maintenance, TaskKind.security]),
            OpsTask.created_at >= since,
        )
    ) or 0
    incident_penalty = min(15, incidents * 3)

    score = 0.6 * (rating / 5 * 100) + 0.2 * aspect_score + 0.2 * uptime_score - incident_penalty
    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "reviews": len(reviews),
        "components": {
            "avg_rating": round(rating, 2),
            "aspect_score": round(aspect_score, 1),
            "power_uptime": uptime,
            "incidents_90d": incidents,
        },
        "weak_aspects": negatives,
        "coaching": [COACHING_TIPS[a] for a in negatives],
    }


def apply_quality_actions(db: Session, prop: Property) -> dict:
    result = score_property(db, prop)
    score = result["score"]
    prop.quality_score = score
    if score is None or prop.status == PropertyStatus.draft:
        return result
    if score < DELIST_BELOW and result["reviews"] >= MIN_REVIEWS_TO_DELIST:
        prop.status = PropertyStatus.suspended
        prop.status_reason = f"Quality score {score} — delisted pending inspection"
    elif score < COACHING_BELOW:
        if prop.status != PropertyStatus.suspended:
            prop.status = PropertyStatus.coaching
            prop.status_reason = "Coaching: " + ("; ".join(result["coaching"]) or "improve guest ratings")
    elif prop.status == PropertyStatus.coaching:
        prop.status, prop.status_reason = PropertyStatus.active, None
    result["status"] = prop.status.value
    return result
