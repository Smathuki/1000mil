"""Market catalogue: launch cities, their seasonality and local currencies.

Seasonality profiles encode well-known East African patterns:
- Safari circuits peak with the Great Migration (Jul–Oct) and the Dec–Feb dry season,
  and slump in the long rains (Apr–May).
- Coast/islands (Zanzibar, Diani) follow a similar dry-season peak plus Christmas/New Year.
- Business capitals (Nairobi, Kigali, Addis, Kampala, Dar) are flatter; events drive surges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Monthly multipliers, index 0 = January.
SAFARI = [1.20, 1.15, 1.00, 0.75, 0.75, 0.95, 1.30, 1.40, 1.35, 1.20, 0.90, 1.25]
COAST = [1.20, 1.10, 1.00, 0.70, 0.70, 0.90, 1.15, 1.20, 1.10, 1.00, 0.95, 1.35]
BUSINESS = [0.95, 1.00, 1.05, 1.00, 0.95, 1.00, 1.00, 1.00, 1.05, 1.10, 1.10, 1.05]


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    country: str
    currency: str
    lat: float
    lng: float
    airport: str
    profile: str  # "safari" | "coast" | "business"
    weekend_uplift: float  # leisure markets price up Fri/Sat nights

    def season_multiplier(self, day: date) -> float:
        table = {"safari": SAFARI, "coast": COAST, "business": BUSINESS}[self.profile]
        return table[day.month - 1]


MARKETS: dict[str, Market] = {
    m.key: m
    for m in [
        Market("nairobi", "Nairobi", "KE", "KES", -1.2864, 36.8172, "NBO", "business", 0.00),
        Market("maasai-mara", "Maasai Mara", "KE", "KES", -1.4061, 35.0089, "MRE", "safari", 0.05),
        Market("diani", "Diani Beach", "KE", "KES", -4.2797, 39.5947, "UKA", "coast", 0.10),
        Market("zanzibar", "Zanzibar", "TZ", "TZS", -6.1659, 39.2026, "ZNZ", "coast", 0.10),
        Market("arusha", "Arusha & Serengeti gateway", "TZ", "TZS", -3.3869, 36.6830, "JRO", "safari", 0.05),
        Market("dar-es-salaam", "Dar es Salaam", "TZ", "TZS", -6.7924, 39.2083, "DAR", "business", 0.00),
        Market("kigali", "Kigali", "RW", "RWF", -1.9441, 30.0619, "KGL", "business", 0.00),
        Market("kampala", "Kampala & Entebbe", "UG", "UGX", 0.3476, 32.5825, "EBB", "business", 0.00),
        Market("addis-ababa", "Addis Ababa", "ET", "ETB", 8.9806, 38.7578, "ADD", "business", 0.00),
    ]
}

# Indicative USD → local rates; production pulls these from a rates provider daily.
FX_PER_USD: dict[str, float] = {
    "USD": 1.0,
    "KES": 129.0,
    "TZS": 2650.0,
    "RWF": 1420.0,
    "UGX": 3680.0,
    "ETB": 125.0,
}


def get_market(key: str) -> Market:
    try:
        return MARKETS[key]
    except KeyError as exc:  # pragma: no cover - guarded by API validation
        raise ValueError(f"Unknown market '{key}'") from exc


def to_local(amount_cents_usd: int, currency: str) -> int:
    """Convert USD cents to whole units of a local currency (rounded up, as mobile money needs integers)."""
    rate = FX_PER_USD[currency]
    value = amount_cents_usd * rate / 100
    return int(value) if value == int(value) else int(value) + 1
