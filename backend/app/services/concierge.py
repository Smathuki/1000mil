"""Upsell catalogue and local recommendations surfaced in the guest app."""

from __future__ import annotations

from ..models import TaskKind

UPSELLS: dict[str, dict] = {
    "airport_transfer": {"title": "Private airport transfer (SUV, meet & greet)", "price_cents": 6500, "task": TaskKind.transfer},
    "private_chef": {"title": "Private chef dinner for up to 6", "price_cents": 18000, "task": TaskKind.chef},
    "grocery_prestock": {"title": "Pantry & fridge pre-stock", "price_cents": 4500, "task": TaskKind.concierge},
    "in_villa_spa": {"title": "In-villa massage (2 × 60 min)", "price_cents": 14000, "task": TaskKind.concierge},
    "game_drive": {"title": "Private game drive with guide", "price_cents": 32000, "task": TaskKind.concierge,
                   "markets": {"maasai-mara", "arusha"}},
    "dhow_cruise": {"title": "Sunset dhow cruise", "price_cents": 12000, "task": TaskKind.concierge,
                    "markets": {"zanzibar", "diani"}},
    "gorilla_permit": {"title": "Gorilla trekking permit & transfer (Volcanoes NP)", "price_cents": 165000,
                       "task": TaskKind.concierge, "markets": {"kigali"}},
    "chauffeur_day": {"title": "Chauffeur on call (10 h)", "price_cents": 15000, "task": TaskKind.transfer,
                      "markets": {"nairobi", "kigali", "kampala", "dar-es-salaam", "addis-ababa"}},
}

RECOMMENDATIONS: dict[str, list[dict]] = {
    "nairobi": [
        {"name": "Nairobi National Park sunrise drive", "type": "experience"},
        {"name": "Giraffe Centre & Karen Blixen Museum", "type": "experience"},
        {"name": "Dinner at Talisman, Karen", "type": "dining"},
        {"name": "Nairobi Street Kitchen, Westlands", "type": "nightlife"},
    ],
    "maasai-mara": [
        {"name": "Hot-air balloon safari at dawn", "type": "experience"},
        {"name": "Maasai village visit with a community guide", "type": "culture"},
    ],
    "zanzibar": [
        {"name": "Stone Town spice & history walk", "type": "culture"},
        {"name": "Mnemba Atoll snorkelling", "type": "experience"},
        {"name": "The Rock Restaurant, Michamvi", "type": "dining"},
    ],
    "diani": [{"name": "Kisite-Mpunguti marine park dhow trip", "type": "experience"}],
    "arusha": [{"name": "Ngorongoro Crater day trip", "type": "experience"}],
    "kigali": [
        {"name": "Kigali Genocide Memorial", "type": "culture"},
        {"name": "Kimironko Market", "type": "culture"},
        {"name": "Heaven Restaurant", "type": "dining"},
    ],
    "kampala": [{"name": "Source of the Nile, Jinja day trip", "type": "experience"}],
    "dar-es-salaam": [{"name": "Bongoyo Island beach escape", "type": "experience"}],
    "addis-ababa": [{"name": "Traditional coffee ceremony & Merkato tour", "type": "culture"}],
}


def catalogue(city: str) -> list[dict]:
    return [
        {"sku": sku, "title": u["title"], "price_cents": u["price_cents"]}
        for sku, u in UPSELLS.items()
        if "markets" not in u or city in u["markets"]
    ]
