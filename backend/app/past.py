"""The home before today: what the web app's "Before" view shows for each risk.

Nothing here scores and no score changes. Each risk gets the number its records give, the
sentence under it and its record, newest first, all from the report's own history:

  - wildfires with a mapped perimeter within 5 km (Government of Catalonia, from 1986) and
    fires seen by satellite within 10 km (Deepfire, from January 2025);
  - flood episodes that affected the municipality (AGORA, 1902-2020) and the wettest days
    of the ERA5 record;
  - avalanches observed within 1 km, or recalled there in ICGC's local surveys;
  - the hottest days of the ERA5 record.

A record that covers the place and holds nothing says so, and a place no record covers
says that instead: an empty tile never reads as a safe one.
"""

from __future__ import annotations

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# How many of the hottest or the wettest days a risk's record lists.
EXTREME_DAYS = 5
# From these extremes, the sentence at the top counts the heat or the rain.
HOT_DAY_C = 35.0
HEAVY_RAIN_MM = 50.0

ERA5 = "ERA5 reanalysis (Copernicus)"
TEXT = "What the records show near this address."
# Avalanches recalled in ICGC's local surveys carry no date, so nothing of them can be
# listed in the record: the note says so rather than leaving the column reading "nothing".
SURVEYED_NOTE = ("Avalanches recalled in ICGC's local surveys carry no date, so they are "
                 "counted here but not listed below.")


def _day(iso: str | None) -> str:
    """'2024-10-29' -> '29 Oct 2024'; a year stays a year."""
    text = str(iso or "")
    parts = text[:10].split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{int(parts[2])} {MONTHS[int(parts[1]) - 1]} {parts[0]}"
    return text


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _indicator(report: dict, card: str, key: str) -> dict | None:
    hazard = next((h for h in report.get("hazards", []) if h["key"] == card), None)
    return next((i for i in (hazard or {}).get("indicators", []) if i["key"] == key), None)


def _count(ind: dict | None) -> int:
    return int(round((ind or {}).get("value") or 0))


def _start(ind: dict | None) -> str:
    """The first year of an indicator's period."""
    return str(((ind or {}).get("provenance") or {}).get("period") or "")[:4]


def _since(report: dict) -> str:
    return ((report.get("window") or {}).get("full_record") or "").split("-")[0] or "1979"


def _kind(items: list[dict], *kinds: str) -> list[dict]:
    return [i for i in items if i.get("kind") in kinds]


def _newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("date") or "", reverse=True)


def _extremes(days: list[dict], family: str, kind: str, first: str, other: str,
              value: str) -> list[dict]:
    """The record's hottest or wettest days, each saying where it ranks ("the 2nd hottest");
    days with the same value share their rank ("the joint 3rd hottest")."""
    days = days[:EXTREME_DAYS]
    values = [d["value"] for d in days]
    rows = []
    for d in days:
        rank = 1 + sum(v > d["value"] for v in values)
        joint = "joint " if values.count(d["value"]) > 1 else ""
        place = first if rank == 1 else f"{_ordinal(rank)} {other}"
        rows.append({"date": d["date"], "family": family, "kind": kind,
                     "title": f"{value.format(d['value'])}, the {joint}{place}", "detail": None,
                     "source": ERA5})
    return rows


def _none(fact: str) -> dict:
    return {"available": False, "value": None, "unit": None, "fact": fact, "phrase": None,
            "record": [], "notes": []}


# --------------------------------------------------------------------------- #
# One risk at a time
# --------------------------------------------------------------------------- #
def _wildfire(report: dict, items: list[dict]) -> dict:
    mapped = _indicator(report, "fire_history", "fires_5km")
    seen = _indicator(report, "wildfire", "satellite_fires_10km")
    record = _kind(items, "mapped_fire", "satellite_fire")
    notes = ["Satellites miss small fires and also see farm burns."] if _count(seen) else []
    if _count(mapped):
        n = _count(mapped)
        return {"available": True, "value": str(n), "unit": _plural(n, "fire"),
                "fact": f"Mapped wildfires within 5 km since {_start(mapped)}.",
                "phrase": "wildfires", "record": record, "notes": notes}
    if _count(seen):
        n = _count(seen)
        return {"available": True, "value": str(n), "unit": _plural(n, "fire"),
                "fact": f"Seen by satellite within 10 km since {_start(seen)}.",
                "phrase": "fires", "record": record, "notes": notes}
    if mapped:
        return _none("No wildfires on record within 5 km.")
    if seen:
        return _none("No fires seen by satellite within 10 km.")
    return _none("No fire record covers this address.")


def _flood(report: dict, items: list[dict]) -> dict:
    episodes = _indicator(report, "flood_history", "flood_episodes")
    wettest = (report.get("events") or {}).get("wettest_days") or []
    since = _since(report)
    rain = _extremes(wettest, "flood", "wettest_day", f"most since {since}", "most",
                     "{:.0f} mm of rain in one day")
    record = _newest_first(_kind(items, "flood_episode") + rain)
    notes = [f"Rain is the daily total over the ~9 km cell of the ERA5 climate record, since {since}."
             ] if rain else []
    heavy = bool(wettest) and wettest[0]["value"] >= HEAVY_RAIN_MM
    if _count(episodes):
        n = _count(episodes)
        return {"available": True, "value": str(n), "unit": _plural(n, "flood"),
                "fact": f"Flood episodes in the municipality since {_start(episodes)}.",
                "phrase": "floods", "record": record, "notes": notes}
    if wettest:
        top = wettest[0]
        return {"available": True, "value": f"{top['value']:.0f}", "unit": "mm",
                "fact": f"The wettest day since {since}, on {_day(top['date'])}.",
                "phrase": "heavy rain" if heavy else None, "record": record, "notes": notes}
    return _none("No flood record covers this address.")


def _heat(report: dict) -> dict:
    hottest = (report.get("events") or {}).get("hottest_days") or []
    if not hottest:
        return _none("No temperature record covers this address.")
    since = _since(report)
    top = hottest[0]
    record = _newest_first(_extremes(hottest, "heat", "hottest_day", f"hottest day since {since}",
                                     "hottest", "{:.1f} °C"))
    return {"available": True, "value": f"{top['value']:.0f}", "unit": "°C",
            "fact": f"The hottest day since {since}, on {_day(top['date'])}.",
            "phrase": "extreme heat" if top["value"] >= HOT_DAY_C else None, "record": record,
            "notes": [f"The daily maximum over the ~9 km cell of the ERA5 climate record, since {since}."]}


def _avalanche(report: dict, items: list[dict], tile: dict | None) -> dict:
    observed = _indicator(report, "avalanche", "avalanche_observed")
    surveyed = _indicator(report, "avalanche", "avalanche_surveyed")
    record = _kind(items, "avalanche")
    if _count(observed):
        n = _count(observed)
        since = f" since {_start(observed)}" if _start(observed) else ""
        return {"available": True, "value": str(n), "unit": _plural(n, "avalanche"),
                "fact": f"Observed within 1 km{since}.", "phrase": "avalanches",
                "record": record, "notes": []}
    # ICGC's database has no observation here, but its surveys collected avalanches the
    # people who live here remember. Counting them keeps the tile from saying "none"
    # while the story beside it lists them.
    if _count(surveyed):
        n = _count(surveyed)
        return {"available": True, "value": str(n), "unit": _plural(n, "avalanche"),
                "fact": "Recalled by local people within 1 km.", "phrase": "avalanches",
                "record": record, "notes": [SURVEYED_NOTE],
                "empty": "No dated avalanche on record near this address."}
    # A place without slopes or snow keeps saying why.
    if tile and tile.get("ruled_out") and tile.get("fact"):
        return _none(tile["fact"])
    if observed or surveyed:
        return _none("No avalanche observed or recalled within 1 km.")
    return _none("No avalanche record covers this address.")


# --------------------------------------------------------------------------- #
# The view
# --------------------------------------------------------------------------- #
def build(report: dict, tiles: list[dict]) -> dict:
    """The "Before" view: a sentence for the top of the page and one entry per risk."""
    items = (report.get("history") or {}).get("items") or []
    by_key = {t["key"]: t for t in tiles}
    risks = {
        "wildfire": _wildfire(report, items),
        "flood": _flood(report, items),
        "avalanche": _avalanche(report, items, by_key.get("avalanche")),
        "heat": _heat(report),
    }
    # At most three, so the title takes no more lines than today's and the page keeps its
    # height; the heat, the last one, is the first to go.
    seen = [r["phrase"] for r in risks.values() if r.get("phrase")][:3]
    title = f"This area has seen {_join(seen)}." if seen else "Nothing extreme on record near this home."
    return {"title": title, "text": TEXT, "risks": risks}
