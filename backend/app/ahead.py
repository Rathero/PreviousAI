"""The home around 2050: what the web app's "2050" view shows for each risk.

Nothing here scores and no score changes. Two sources give a CHANGE between two windows
of the same climate models, and that change is carried onto today's value from the record:

  - CMIP6 HighResMIP (Open-Meteo Climate API), 1995-2014 against 2036-2050, forcing close
    to SSP5-8.5: days above 35 and 32 °C and tropical nights (the change in days is added
    to ERA5's count) and the wettest day of a typical year (its change in per cent is
    applied to ERA5's, as rain changes are relative);
  - Copernicus fire danger (EURO-CORDEX), 1981-2005 against 2041-2060: days a year of high
    fire danger (FWI above 30), shown as the models give them. It is not the index behind
    today's fire score, so the two are never mixed.

Official maps and records (flood zones, mapped fires, avalanche paths) describe today and
no source projects them: the view says so instead of repeating their score.
"""

from __future__ import annotations

from . import scoring

# Smaller changes are "about the same". Days above 35 °C have the heat scale to judge a
# change by (5 points on it); tropical nights and days above 32 °C do not, so a change
# has to reach five a year: a mountain town going from none to three warm nights stays
# a place where they are rare.
MIN_DAYS = 1.0
MIN_HEAT_POINTS = 5.0
MIN_OTHER_DAYS = 5.0
MIN_FIRE_DAYS = 2.0
MIN_RAIN_PCT = 3.0

STORY_TITLES = {"wildfire": "Fire near this home in 2050", "flood": "Water near this home in 2050",
                "heat": "Heat at this home in 2050", "avalanche": "Avalanches near this home in 2050"}

# Heat metrics in the order they can lead: the scored one first, then the nights (the heat
# that grows by the sea), then the milder threshold.
HEAT_METRICS = [
    {"key": "hot_days_35", "label": "Days a year above 35 °C", "unit": "days",
     "what": "days above 35 °C a year", "phrase": "heat"},
    {"key": "tropical_nights", "label": "Tropical nights a year (never below 20 °C)", "unit": "nights",
     "what": "tropical nights a year", "phrase": "warm nights"},
    {"key": "hot_days_32", "label": "Days a year above 32 °C", "unit": "days",
     "what": "days above 32 °C a year", "phrase": "hot days"},
]

SCENARIO_NOTE = ("If emissions stay high. Climate models give the change between two windows "
                 "of the same models, carried onto today's record; their own values are not "
                 "used.")


def _dash(period: str | None) -> str:
    return (period or "").replace("-", "–")


def _num(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 10:
        return f"{value:.0f}"
    if abs(value) < 0.05:
        return "0"
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _signed(value: float, unit: str = "") -> str:
    rounded = round(value)
    sign = "+" if rounded > 0 else "−" if rounded < 0 else ""
    return f"{sign}{abs(rounded)}{unit}"


def _hazard(report: dict, key: str) -> dict | None:
    return next((h for h in report.get("hazards", []) if h["key"] == key), None)


def _indicator(hazard: dict | None, key: str) -> dict | None:
    return next((i for i in (hazard or {}).get("indicators", []) if i["key"] == key), None)


def _metric(hazard: dict | None, key: str) -> dict | None:
    return next((m for m in ((hazard or {}).get("projection") or {}).get("metrics", [])
                 if m["key"] == key), None)


def _direction(change: float, minimum: float) -> str:
    return "up" if change >= minimum else "down" if change <= -minimum else "same"


def _material(key: str, today: float, future: float) -> bool:
    if abs(future - today) < MIN_DAYS:
        return False
    if key == "hot_days_35":
        points = (scoring.score_for("heat", future) or 0) - (scoring.score_for("heat", today) or 0)
        return abs(points) >= MIN_HEAT_POINTS
    return abs(future - today) >= MIN_OTHER_DAYS


def _unavailable(fact: str) -> dict:
    return {"available": False, "direction": None, "change": None, "fact": fact, "rows": [],
            "notes": []}


# --------------------------------------------------------------------------- #
# One risk at a time
# --------------------------------------------------------------------------- #
def _heat(report: dict) -> dict:
    card = _hazard(report, "heat")
    proj = (card or {}).get("projection") or {}
    today_label = _dash((report.get("window") or {}).get("climatology"))
    future_label = _dash(proj.get("future_period"))
    rows, lead = [], None
    for m in HEAT_METRICS:
        ind, metric = _indicator(card, m["key"]), _metric(card, m["key"])
        if not ind or ind.get("value") is None or not metric:
            continue
        today = float(ind["value"])
        future = max(0.0, today + float(metric["delta"]))
        change = future - today
        rows.append({"label": m["label"], "from": _num(today), "to": _num(future),
                     "change": _signed(change) if abs(change) >= MIN_DAYS else "about the same"})
        if lead is None and _material(m["key"], today, future):
            lead = (m, today, future, change)
    if not rows:
        return _unavailable("No heat projection for this place in our sources.")
    out = {"available": True, "rows": rows, "title": STORY_TITLES["heat"],
           "periods": f"Today: the ERA5 record, {today_label}. 2050: {future_label}.",
           "notes": [], "source": "CMIP6 HighResMIP · ERA5"}
    if lead:
        m, today, future, change = lead
        out.update(direction="up" if change > 0 else "down", change=f"{_signed(change)} {m['unit']}",
                   fact=f"{'More' if change > 0 else 'Fewer'} {m['what']} by {future_label}.",
                   phrase=m["phrase"],
                   highlight={"number": _signed(change),
                              "text": f"{m['what']} by {future_label} ({_num(today)} → {_num(future)})."},
                   bars={"from": {"value": round(today, 1), "label": "Today"},
                         "to": {"value": round(future, 1), "label": "2050"}})
    else:
        rare = (card.get("score") or 0) < 20
        out.update(direction="same", change="Stays low" if rare else "Little change",
                   fact=("Heat stays rare here by " if rare else "Little change is projected by ")
                   + f"{future_label}.")
    return out


def _flood(report: dict) -> dict:
    rain = _hazard(report, "rain")
    ind, metric = _indicator(rain, "rx1day"), _metric(rain, "rx1day")
    notes = []
    zone = _hazard(report, "flood_zone")
    if zone and (zone.get("score") or 0) > 0:
        notes.append(f"{zone['headline'].rstrip('.')}: the official flood map describes today "
                     f"and no source projects it.")
    sea = _hazard(report, "sea_level")
    if sea:
        notes.append(sea["headline"].rstrip(".") + " (ICGC models rises of up to 85 cm).")
    history = _hazard(report, "flood_history")
    if history and (history.get("score") or 0) > 0:
        notes.append("Past flood episodes describe the record; they are not projected.")
    if not ind or ind.get("value") is None or not metric or metric.get("pct_change") is None:
        out = _unavailable("No rain projection for this place in our sources.")
        out["notes"] = notes
        return out
    proj = rain.get("projection") or {}
    future_label = _dash(proj.get("future_period"))
    today = float(ind["value"])
    pct = float(metric["pct_change"])
    future = today * (1 + pct / 100)
    direction = _direction(pct, MIN_RAIN_PCT)
    return {
        "available": True, "direction": direction,
        "change": f"{_signed(pct)} %" if direction != "same" else "No change",
        "fact": ("More rain on the wettest day of the year" if direction == "up" else
                 "Less rain on the wettest day of the year" if direction == "down" else
                 "The wettest day of the year barely changes") + f" by {future_label}.",
        "phrase": "heavy rain",
        "highlight": {"number": f"{_signed(pct)} %",
                      "text": f"rain on the wettest day of the year by {future_label} "
                              f"({_num(today)} → {_num(future)} mm)."},
        "bars": {"from": {"value": round(today), "label": "Today"},
                 "to": {"value": round(future), "label": "2050"}, "unit": "mm"},
        "title": STORY_TITLES["flood"],
        "rows": [{"label": "Rain on the wettest day of a typical year", "from": f"{_num(today)} mm",
                  "to": f"{_num(future)} mm", "change": f"{_signed(pct)} %"}],
        "periods": (f"Today: the ERA5 record, {_dash((report.get('window') or {}).get('climatology'))}. "
                    f"2050: {future_label}."),
        "notes": notes, "source": "CMIP6 HighResMIP · ERA5",
    }


def _wildfire(report: dict) -> dict:
    card = _hazard(report, "wildfire")
    base = _indicator(card, "fwi_high_historical_1981_2005")
    high = _indicator(card, "fwi_high_rcp8_5_2041_2060")
    mid = _indicator(card, "fwi_high_rcp4_5_2041_2060")
    notes = ["Mapped wildfires and fires seen by satellite describe the past; they are not "
             "projected.",
             "This fire-danger index (FWI) is not the fire weather behind today's score, so the "
             "score is not recomputed."]
    if not base or base.get("value") is None or not high or high.get("value") is None:
        out = _unavailable("No fire-danger projection for this place in our sources.")
        out["notes"] = notes[:1]
        return out
    then, future = float(base["value"]), float(high["value"])
    change = future - then
    direction = _direction(change, MIN_FIRE_DAYS)
    rows = [{"label": "Days a year of high fire danger (FWI above 30), if emissions stay high",
             "from": _num(then), "to": _num(future), "change": _signed(change)}]
    if mid and mid.get("value") is not None:
        rows.append({"label": "The same, if emissions are cut to an intermediate path",
                     "from": _num(then), "to": _num(float(mid["value"])),
                     "change": _signed(float(mid["value"]) - then)})
    return {
        "available": True, "direction": direction,
        "change": f"{_signed(change)} days" if direction != "same" else "No change",
        "fact": ("More days of high fire danger a year" if direction == "up" else
                 "Fewer days of high fire danger a year" if direction == "down" else
                 "Days of high fire danger barely change") + " by 2041–2060.",
        "phrase": "fire danger",
        "highlight": {"number": _signed(change),
                      "text": f"days a year of high fire danger by 2041–2060 "
                              f"({_num(then)} in 1981–2005, {_num(future)} then)."},
        "bars": {"from": {"value": round(then, 1), "label": "1981–2005"},
                 "to": {"value": round(future, 1), "label": "2050"}},
        "title": STORY_TITLES["wildfire"],
        "rows": rows,
        "periods": "Copernicus fire-danger projection, 1981–2005 against 2041–2060.",
        "notes": notes, "source": "Copernicus Climate Change Service (EURO-CORDEX)",
    }


def _avalanche(tile: dict | None) -> dict:
    """No source here projects avalanches; a place without slopes keeps saying why."""
    if tile and tile.get("ruled_out") and tile.get("fact"):
        return _unavailable(tile["fact"])
    return _unavailable("No 2050 projection for avalanches in our sources.")


# --------------------------------------------------------------------------- #
# The view
# --------------------------------------------------------------------------- #
def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _highlight(key: str, risk: dict) -> dict | None:
    """One line of "What changes by 2050": the number, then what it counts."""
    if not risk.get("available") or risk.get("direction") not in ("up", "down"):
        return None
    return {"family": key, **risk["highlight"]}


def build(report: dict, tiles: list[dict]) -> dict:
    """The 2050 view: a sentence for the top of the page and one entry per risk."""
    by_key = {t["key"]: t for t in tiles}
    risks = {
        "wildfire": _wildfire(report),
        "flood": _flood(report),
        "avalanche": _avalanche(by_key.get("avalanche")),
        "heat": _heat(report),
    }
    for key, risk in risks.items():
        risk.setdefault("title", STORY_TITLES[key])
    growing = [r["phrase"] for k, r in risks.items() if r.get("direction") == "up" and r.get("phrase")]
    # "Little change" is a finding, and it needs a projection behind it. With none of the
    # four available the page has nothing to report, and must say that instead.
    known = any(r.get("available") for r in risks.values())
    # Short enough to take no more lines than today's title, so the page keeps its height.
    title = (f"By 2050: more {_join(growing)}." if growing
             else "By 2050: little change here." if known
             else "By 2050: we have no projection for this address.")
    text = ("What climate models project if emissions stay high." if known
            else "The climate models could not be read for this point. Nothing here says "
                 "the risks stay as they are.")
    highlights = [h for h in (_highlight(k, risks[k]) for k in ("wildfire", "flood", "heat")) if h]
    return {"title": title, "text": text, "risks": risks, "highlights": highlights,
            "scenario": SCENARIO_NOTE}
