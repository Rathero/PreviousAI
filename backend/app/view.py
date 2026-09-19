"""The report as the web app shows it: the home, four risks, the history and the plan.

A compact projection of the full report (`report.build_report`): nothing is computed
here that is not already in the report, and every number keeps its source.
"""

from __future__ import annotations

from . import protection

# The four risk tiles, in the order the app lays them out.
TILES = [("wildfire", "Wildfires"), ("flood", "Floods"), ("avalanche", "Avalanches"),
         ("heat", "Heat waves")]


_PARTICLES = {"de", "del", "dels", "la", "las", "los", "les", "el", "els", "i", "y", "d", "l"}


def street_name(text: str | None) -> str | None:
    """Joining words in lower case inside each part of an address, and each part opening
    with a capital: "Passeig Prat De La Riba 10, el Masnou" -> "Passeig Prat de la Riba 10,
    El Masnou" (some saved addresses were title-cased word by word)."""
    if not text:
        return text
    parts = []
    for part in text.split(","):
        lead, words = part[: len(part) - len(part.lstrip())], part.strip().split(" ")
        name = " ".join(w.lower() if i and w.lower() in _PARTICLES else w for i, w in enumerate(words))
        parts.append(lead + name[:1].upper() + name[1:])
    return ",".join(parts)


def _town(loc: dict) -> str | None:
    if loc.get("town"):
        return loc["town"]
    parts = [p.strip() for p in str(loc.get("label") or "").split(",") if p.strip()]
    return parts[1] if len(parts) > 1 else None


def place_lines(loc: dict) -> dict:
    """The two lines of the address header: the street (or the town) and where it is.
    A town on its own is followed by its region, not by its own name again."""
    name = street_name(loc.get("name"))
    town = street_name(_town(loc))
    if not town or (name and town.lower() == name.lower()):
        town = loc.get("admin1") or loc.get("country")
    return {"name": name, "town": town}


def _source(card: dict) -> str | None:
    """Where the card's leading value comes from."""
    inds = card.get("indicators") or []
    primary = next((i for i in inds if i.get("key") == card.get("primary_metric")), None)
    ind = primary or (inds[0] if inds else None)
    return ((ind or {}).get("provenance") or {}).get("source")


def _illustration(cards: list[dict]) -> dict | None:
    """The clip of the family's worst card that has one."""
    for card in cards:
        ill = card.get("illustration")
        if ill:
            c = ill.get("chosen_by") or {}
            return {"video": ill["video"], "poster": ill.get("poster"), "title": ill["title"],
                    "caption": ill["caption"], "card": card["label"],
                    "chosen_by": {k: c.get(k) for k in ("label", "shown", "rule", "source")},
                    "models": {k: (ill.get("generated_with") or {}).get(k)
                               for k in ("image_model", "video_model")},
                    "limitation": ill.get("limitation")}
    return None


def _tile(report: dict, key: str, label: str, family: dict | None) -> dict:
    card_keys = protection.FAMILIES[key]["cards"]
    cards = sorted((h for h in report.get("hazards", [])
                    if h["key"] in card_keys and h.get("score") is not None),
                   key=lambda h: -h["score"])
    top = cards[0] if cards else None
    notes = ((report.get("dwelling") or {}).get("notes") or {})
    return {
        "key": key,
        "label": label,
        "applies": bool(top),
        "ruled_out": bool((family or {}).get("ruled_out")),
        "score": round(top["score"]) if top else (0 if (family or {}).get("ruled_out") else None),
        "level": top["level"] if top else None,
        "summary": top["headline"] if top else (family or {}).get("note"),
        "source": _source(top) if top else None,
        "cards": [{"key": c["key"], "label": c["label"], "score": round(c["score"]),
                   "level": c["level"], "headline": c["headline"], "source": _source(c),
                   "scales": c.get("scales"), "limitation": c.get("limitation")} for c in cards],
        "home_note": notes.get(key),
        "illustration": _illustration(cards),
    }


def risks(report: dict) -> list[dict]:
    """The four risk tiles, in the app's order."""
    families = {f["key"]: f for f in (report.get("protection") or {}).get("families", [])}
    return [_tile(report, key, label, families.get(key)) for key, label in TILES]


def app_view(report: dict) -> dict:
    loc = report["location"]
    return {
        "location": {
            "label": street_name(loc.get("label")), **place_lines(loc),
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "precision": loc.get("precision"), "geocoder": loc.get("geocoder"),
            "ref_catastral": loc.get("ref_catastral"), "country": loc.get("country"),
            "address_not_found": loc.get("address_not_found"),
            "elevation_m": loc.get("elevation_m"),
        },
        "dwelling": report.get("dwelling"),
        "overall": report.get("overall"),
        "risks": risks(report),
        "history": report.get("history"),
        "action_plan": report.get("action_plan"),
        "aerial": (report.get("map") or {}).get("aerial"),
        "zoom": (report.get("map") or {}).get("zoom"),
        "notes": (report.get("coverage") or {}).get("notes", []),
        "personalization": report.get("personalization"),
        "warnings": report.get("warnings", []),
        "sources": [{"name": s["name"], "url": s.get("url")} for s in report.get("sources", [])],
        "meta": report.get("meta"),
    }
