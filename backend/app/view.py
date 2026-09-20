"""The report as the web app shows it: the home, four risks, what happened and the plan.

A compact projection of the full report (`report.build_report`): nothing is computed
here that is not already in the report, and every number keeps its source. The only
additions are words: the sentence that sums the four risks up, one short fact per risk
and the rows of what already happened near the home.
"""

from __future__ import annotations

import datetime as dt
import re

from . import ahead, grants, past, products, protection, simulations
from .hazards_official import ZONE_ORDER, ZONE_SHORT

# The four risk tiles, in the order the app lays them out.
TILES = [("wildfire", "Fire"), ("flood", "Flooding"), ("avalanche", "Avalanches"),
         ("heat", "Heat waves")]

# From this score a risk gets its own plan: it is "worth preparing for".
WORTH = 20

STORY_TITLES = {"wildfire": "Fire near this home", "flood": "Water near this home",
                "heat": "Heat at this home", "avalanche": "Avalanches near this home"}

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
COUNT_WORDS = {1: "One thing is", 2: "Two things are", 3: "Three things are", 4: "Four things are"}
PLURAL = {"avalanche", "heat"}   # "Heat waves are", "Avalanches are"

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


# --------------------------------------------------------------------------- #
# Reading the report
# --------------------------------------------------------------------------- #
def _card(report: dict, key: str) -> dict | None:
    return next((h for h in report.get("hazards", []) if h["key"] == key), None)


def _indicator(report: dict, card: str, key: str) -> dict | None:
    return next((i for i in (_card(report, card) or {}).get("indicators", []) if i["key"] == key), None)


def _count(report: dict, card: str, key: str) -> tuple[int, str] | None:
    """(value, first year of its period) of a counted indicator, when it counts something."""
    ind = _indicator(report, card, key)
    if not ind or not ind.get("value"):
        return None
    return int(round(ind["value"])), str((ind.get("provenance") or {}).get("period") or "")[:4]


def _source(card: dict) -> str | None:
    """Where the card's leading value comes from."""
    inds = card.get("indicators") or []
    primary = next((i for i in inds if i.get("key") == card.get("primary_metric")), None)
    ind = primary or (inds[0] if inds else None)
    return ((ind or {}).get("provenance") or {}).get("source")


def _since(report: dict) -> str:
    return ((report.get("window") or {}).get("full_record") or "").split("-")[0] or "1979"


def _km(value_km: float) -> str:
    return f"{value_km * 1000:.0f} m" if value_km < 1 else f"{value_km:.1f} km"


def _degrees(text: str) -> str:
    return re.sub(r"(\d+) degrees", r"\1 °C", text)


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


# --------------------------------------------------------------------------- #
# One fact per tile, and what happened near the home
# --------------------------------------------------------------------------- #
def _satellite_fires(report: dict) -> list[dict]:
    fires = (report.get("events") or {}).get("satellite_fires") or []
    return sorted((f for f in fires if f.get("first")), key=lambda f: f["first"], reverse=True)


def _mapped_fires(report: dict) -> list[dict]:
    fires = (report.get("events") or {}).get("nearby_fires") or []
    return sorted(fires, key=lambda f: f.get("date") or str(f.get("year") or ""), reverse=True)


def _flood_zone(report: dict) -> str | None:
    """The most frequent official flood zone the home is inside, if any."""
    for k in ZONE_ORDER:
        ind = _indicator(report, "flood_zone", f"flood_zone_{k}")
        if ind and ind.get("value") == 1:
            return ZONE_SHORT[k]
    for k, name in (("marine_t100", "100-year coastal flood zone"),
                    ("marine_t500", "500-year coastal flood zone")):
        ind = _indicator(report, "flood_zone", f"flood_zone_{k}")
        if ind and ind.get("value"):
            return name
    return None


def _first_clause(text: str) -> str:
    clause = _degrees(text.split(";")[0].strip())
    return clause[:1].upper() + clause[1:] + ("" if clause.endswith(".") else ".")


def _fact(report: dict, key: str, top: dict | None, ruled_out_note: str | None) -> str | None:
    """One short sentence under the tile's score."""
    events = report.get("events") or {}
    if key == "wildfire":
        sat = _satellite_fires(report)
        if sat:
            f, day = sat[0], dt.date.fromisoformat(sat[0]["first"][:10])
            when = (f"this {MONTHS[day.month - 1]}" if day.year == dt.date.today().year
                    else f"in {MONTHS[day.month - 1]} {day.year}")
            verb = "burned" if f.get("area_ha") else "was detected"
            return f"A fire {verb} {_km(f['distance_km'])} away {when}."
        mapped = [f for f in _mapped_fires(report) if f.get("distance_m") is not None]
        if mapped:
            near = min(mapped, key=lambda f: f["distance_m"])
            year = near.get("year") or str(near.get("date") or "")[:4]
            if near.get("inside"):
                return f"A mapped wildfire reached this point in {year}."
            return f"The nearest mapped wildfire burned {_km(near['distance_m'] / 1000)} away in {year}."
    elif key == "flood":
        zone = _flood_zone(report)
        if zone:
            return f"Inside the official {zone}."
        wettest = (events.get("wettest_days") or [None])[0]
        if wettest:
            return f"{wettest['value']:.0f} mm of rain fell in one day in {wettest['date'][:4]}."
    elif key == "avalanche" and ruled_out_note:
        return ("No mountain slopes near this address." if "slope" in ruled_out_note
                else "Too little snow here for avalanches.")
    return _first_clause(top["headline"]) if top else None


def _story(report: dict, key: str, cards: list[dict]) -> list[dict]:
    """What already happened near the home for one risk: [{"when", "text"}], at most four
    rows. "when" is an ISO date, a year or a short label ("Since 1986")."""
    events = report.get("events") or {}
    since = _since(report)
    rows: list[dict] = []
    if key == "wildfire":
        for f in _satellite_fires(report)[:2]:
            area = f", about {f['area_ha']:,.0f} hectares" if f.get("area_ha") else ""
            rows.append({"when": f["first"][:10],
                         "text": f"Fire detected by satellite {_km(f['distance_km'])} away{area}."})
        for f in _mapped_fires(report)[: max(0, 2 - len(rows))]:
            size = f"A wildfire of {f['area_ha']:,.0f} hectares" if f.get("area_ha") else "A wildfire"
            where = ("reached this point" if f.get("inside") else
                     f"burned {_km(f['distance_m'] / 1000)} away" if f.get("distance_m") is not None
                     else "burned nearby")
            rows.append({"when": f.get("date") or str(f.get("year") or ""), "text": f"{size} {where}."})
        n = _count(report, "fire_history", "fires_5km")
        if n:
            rows.append({"when": f"Since {n[1]}",
                         "text": f"{n[0]} mapped wildfire{'s' if n[0] != 1 else ''} within 5 km."})
        if not rows and cards:
            rows.append({"when": "Every year", "text": _first_clause(cards[0]["headline"])})
    elif key == "flood":
        dwelling = report.get("dwelling") or {}
        note = (dwelling.get("notes") or {}).get("flood")
        if note:
            rows.append({"when": "Your flat" if dwelling.get("kind") == "apartment" else "Your home",
                         "text": note})
        zone_card = _card(report, "flood_zone")
        if _flood_zone(report) and zone_card:
            rows.append({"when": "Official map", "text": _first_clause(zone_card["headline"])})
        wettest = (events.get("wettest_days") or [None])[0]
        if wettest:
            rows.append({"when": wettest["date"],
                         "text": f"{wettest['value']:.0f} mm of rain in one day, the most since {since}."})
        n = _count(report, "flood_history", "flood_episodes")
        if n:
            rows.append({"when": f"Since {n[1]}",
                         "text": f"{n[0]} flood episode{'s' if n[0] != 1 else ''} recorded in the "
                                 f"municipality."})
    elif key == "heat":
        hottest = (events.get("hottest_days") or [None])[0]
        if hottest:
            rows.append({"when": hottest["date"],
                         "text": f"{hottest['value']:.1f} °C, the hottest day since {since}."})
        if cards:
            for clause in cards[0]["headline"].split(";")[:2]:
                rows.append({"when": "Every year", "text": _first_clause(clause)})
    elif key == "avalanche":
        n = _count(report, "avalanche", "avalanche_observed")
        if n:
            rows.append({"when": f"Since {n[1]}",
                         "text": f"{n[0]} avalanche{'s' if n[0] != 1 else ''} observed within 1 km."})
        if cards:
            for part in (p.strip() for p in cards[0]["headline"].split(";") if p.strip()):
                if n and "observed" in part:
                    continue
                label = ("Every year" if "typical year" in part else
                         "Local surveys" if "recalled" in part else "Official map")
                rows.append({"when": label, "text": _first_clause(part)})
    return rows[:4]


def _highlights(report: dict) -> list[dict]:
    """The three numbers of what has happened around the home."""
    out = []
    n = _count(report, "flood_history", "flood_episodes")
    if n:
        out.append({"number": str(n[0]), "family": "flood", "icon": "waves",
                    "text": f"flood{'s' if n[0] != 1 else ''} in the municipality since {n[1]}."})
    n = _count(report, "fire_history", "fires_5km")
    if n:
        out.append({"number": str(n[0]), "family": "wildfire", "icon": "flame",
                    "text": f"wildfire{'s' if n[0] != 1 else ''} within 5 km since {n[1]}."})
    sat = _satellite_fires(report)
    if sat:
        # The report keeps only the latest fires: the year's count is known when an older
        # fire is listed too, or when the list holds them all; otherwise the whole record.
        total = _count(report, "wildfire", "satellite_fires_10km")
        this_year = [f for f in sat if f["first"][:4] == str(dt.date.today().year)]
        if this_year and (len(this_year) < len(sat) or not total or total[0] <= len(sat)):
            n, when = len(this_year), "this year"
        elif total:
            n, when = total[0], f"since {total[1]}"
        else:
            n, when = len(sat), f"since {sat[-1]['first'][:4]}"
        out.append({"number": str(n), "family": "wildfire", "icon": "satellite",
                    "text": f"fire{'s' if n != 1 else ''} seen by satellite within 10 km {when}."})
    n = _count(report, "avalanche", "avalanche_observed")
    if n:
        out.append({"number": str(n[0]), "family": "avalanche", "icon": "mountain",
                    "text": f"avalanche{'s' if n[0] != 1 else ''} observed within 1 km since {n[1]}."})
    else:
        # No observation on file, but ICGC's surveys collected avalanches local people
        # remember: the number says so rather than leaving the risk out of the summary.
        n = _count(report, "avalanche", "avalanche_surveyed")
        if n:
            out.append({"number": str(n[0]), "family": "avalanche", "icon": "mountain",
                        "text": f"avalanche{'s' if n[0] != 1 else ''} within 1 km recalled by "
                                f"local people."})
    events, since = report.get("events") or {}, _since(report)
    hottest = (events.get("hottest_days") or [None])[0]
    if hottest and len(out) < 3:
        out.append({"number": f"{hottest['value']:.0f} °C", "family": "heat", "icon": "sun",
                    "text": f"on the hottest day since {since}, in {hottest['date'][:4]}."})
    wettest = (events.get("wettest_days") or [None])[0]
    if wettest and len(out) < 3:
        out.append({"number": f"{wettest['value']:.0f} mm", "family": "flood", "icon": "rain",
                    "text": f"of rain on the wettest day since {since}, in {wettest['date'][:4]}."})
    return out[:3]


def _names(group: list[dict]) -> str:
    names = [r["label"] if i == 0 else r["label"].lower() for i, r in enumerate(group)]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _verb(group: list[dict]) -> str:
    return "are" if len(group) > 1 or group[0]["key"] in PLURAL else "is"


def headline(tiles: list[dict]) -> dict:
    """The sentence that sums the four risks up, and the line that says how they stand."""
    scored = sorted((r for r in tiles if r["score"] is not None), key=lambda r: -r["score"])
    worth = [r for r in scored if r["score"] >= WORTH]
    calm = [r for r in scored if r["score"] < WORTH]
    title = (f"{COUNT_WORDS[len(worth)]} worth preparing for at your home." if worth
             else "Nothing here calls for special preparation.")
    groups: list[tuple[str, list[dict]]] = []
    for r in worth:
        if groups and groups[-1][0] == r["level"]:
            groups[-1][1].append(r)
        else:
            groups.append((r["level"], [r]))
    sentences = [f"{_names(g)} {_verb(g)} {level}{' here' if i == 0 else ''}."
                 for i, (level, g) in enumerate(groups)]
    if not worth and calm:
        sentences.append(f"{_names(calm)} {_verb(calm)} not a concern here.")
    return {"title": title, "text": " ".join(sentences)}


# --------------------------------------------------------------------------- #
# The view
# --------------------------------------------------------------------------- #
def _tile(report: dict, key: str, label: str, family: dict | None) -> dict:
    card_keys = protection.FAMILIES[key]["cards"]
    cards = sorted((h for h in report.get("hazards", [])
                    if h["key"] in card_keys and h.get("score") is not None),
                   key=lambda h: -h["score"])
    top = cards[0] if cards else None
    notes = ((report.get("dwelling") or {}).get("notes") or {})
    ruled_out = bool((family or {}).get("ruled_out"))
    ruled_out_note = ((report.get("coverage") or {}).get("ruled_out") or {}).get(key)
    score = round(top["score"]) if top else (0 if ruled_out else None)
    return {
        "key": key,
        "label": label,
        "applies": bool(top),
        "ruled_out": ruled_out,
        "score": score,
        "level": top["level"] if top else ("very low" if ruled_out else None),
        "worth": score is not None and score >= WORTH,
        "summary": top["headline"] if top else (family or {}).get("note"),
        "fact": _fact(report, key, top, ruled_out_note if ruled_out else None),
        "story_title": STORY_TITLES[key],
        "story": _story(report, key, cards),
        "source": _source(top) if top else None,
        "cards": [{"key": c["key"], "label": c["label"], "score": round(c["score"]),
                   "level": c["level"], "headline": c["headline"], "source": _source(c),
                   "scales": c.get("scales"), "limitation": c.get("limitation")} for c in cards],
        "home_note": notes.get(key),
        "illustration": _illustration(cards),
    }


def risks(report: dict) -> list[dict]:
    """The four risk tiles, in the app's order. Where the place has simulations drawn on
    its own street photo (simulations.py), they replace the generic illustrations."""
    families = {f["key"]: f for f in (report.get("protection") or {}).get("families", [])}
    tiles = [_tile(report, key, label, families.get(key)) for key, label in TILES]
    for tile in tiles:
        tile["illustration"] = simulations.for_tile(report, tile) or tile["illustration"]
    return tiles


def app_view(report: dict) -> dict:
    loc = report["location"]
    tiles = risks(report)
    history = {**(report.get("history") or {}), "highlights": _highlights(report)}
    future = ahead.build(report, tiles)
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
        "headline": headline(tiles),
        "risks": tiles,
        "past": past.build(report, tiles),
        "ahead": future,
        "grants": grants.for_report(report, tiles, future),
        "advanced_kit": products.advanced_kit(),
        "history": history,
        "action_plan": report.get("action_plan"),
        "aerial": (report.get("map") or {}).get("aerial"),
        "zoom": (report.get("map") or {}).get("zoom"),
        "notes": (report.get("coverage") or {}).get("notes", []),
        "personalization": report.get("personalization"),
        "warnings": report.get("warnings", []),
        "sources": [{"name": s["name"], "url": s.get("url")} for s in report.get("sources", [])],
        "meta": report.get("meta"),
    }
