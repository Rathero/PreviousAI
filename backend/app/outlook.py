"""The next 15 days compared with what is usual for those dates.

Two figures per event, always together:
  - FORECAST: from the ensemble members, how many days of that event are expected in
    the window and in what share of members there is at least one.
  - USUAL: the same from the ERA5 record for the same calendar dates, year by year.

Events: 35 °C days and tropical nights (heat) and 20 mm days (the driver of flash
flooding). Without the usual figure, "60 % chance of a 35 °C day" does not say whether
it is an odd week or any September in Seville. None of this scores.
"""

from __future__ import annotations

import datetime as dt
import statistics

from . import config, series as S

EVENTS = [
    {"key": "heat", "label": "Days of 35 °C or more", "short": "35 °C heat",
     "var": "temperature_2m_max", "op": "ge", "threshold": 35.0},
    {"key": "tropical_night", "label": "Nights of 20 °C or more", "short": "tropical nights",
     "var": "temperature_2m_min", "op": "ge", "threshold": 20.0},
    {"key": "heavy_rain", "label": "Days with 20 mm of rain or more", "short": "heavy rain",
     "var": "precipitation_sum", "op": "ge", "threshold": 20.0},
]

ABOVE, BELOW, USUAL, NO_REFERENCE = "above usual", "below usual", "usual", "no reference"


def _hit(value: float | None, op: str, threshold: float) -> bool:
    if value is None:
        return False
    return value >= threshold if op == "ge" else value <= threshold


def _pct(values: list[float], q: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    return S.percentile(vals, q)


def window_indices(dates: list[str], trip: tuple[dt.date, dt.date] | None,
                   months: set[int] | None = None) -> list[int]:
    """Forecast days inside the window: the dates if there are any, otherwise the months."""
    if trip is not None:
        start, end = trip
        return [i for i, d in enumerate(dates) if start <= dt.date.fromisoformat(d) <= end]
    if months:
        return [i for i, d in enumerate(dates) if int(d[5:7]) in months]
    return list(range(len(dates)))


def forecast_event(members: dict, idx: list[int], ev: dict) -> dict | None:
    """Expected days and probability of at least one, across the members."""
    days = members.get(ev["var"]) or []
    if not idx or not days:
        return None
    n_members = max(len(days[i]) for i in idx)
    if n_members == 0:
        return None
    counts = [0] * n_members
    valid_days = 0
    for i in idx:
        vals = days[i]
        if not any(v is not None for v in vals):
            continue  # a day without data (the last one of some cycles)
        valid_days += 1
        for m, v in enumerate(vals):
            if _hit(v, ev["op"], ev["threshold"]):
                counts[m] += 1
    if valid_days == 0:
        return None
    return {"expected_days": round(sum(counts) / n_members, 1),
            "prob_any": round(sum(1 for c in counts if c) / n_members, 2),
            "days": valid_days, "members": n_members}


def climatology_event(series: S.DailySeries, window: list[dt.date], ev: dict,
                      first_year: int, last_year: int) -> dict | None:
    """Same calendar dates, every year of the record."""
    values = series.get(ev["var"])
    if not values or not window:
        return None
    index = {d: i for i, d in enumerate(series.dates)}
    per_year = []
    for year in range(first_year, last_year + 1):
        hits, seen = 0, 0
        for d in window:
            try:
                day = d.replace(year=year)
            except ValueError:  # 29 February in a non-leap year
                continue
            i = index.get(day)
            if i is None or values[i] is None:
                continue
            seen += 1
            hits += _hit(values[i], ev["op"], ev["threshold"])
        if seen >= len(window) * 0.8:
            per_year.append(hits)
    if len(per_year) < 10:
        return None
    return {"expected_days": round(statistics.mean(per_year), 1),
            "prob_any": round(sum(1 for h in per_year if h) / len(per_year), 2),
            "years": f"{first_year}-{last_year}", "n_years": len(per_year)}


def signal(fc: dict, clim: dict | None) -> str:
    if clim is None:
        return NO_REFERENCE
    f, c = fc["expected_days"], clim["expected_days"]
    if fc["prob_any"] >= 0.2 and f >= 1.5 * c + 0.5:
        return ABOVE
    if c >= 1 and f <= 0.5 * c:
        return BELOW
    return USUAL


def _fmt_date(d: str) -> str:
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    day = dt.date.fromisoformat(d)
    return f"{day.day} {months[day.month]}"


def build(fc: dict, series: S.DailySeries, trip: tuple[dt.date, dt.date] | None = None,
          months: set[int] | None = None) -> dict:
    dates = fc["dates"]
    idx = window_indices(dates, trip, months)
    members = fc["members"]
    window = [dt.date.fromisoformat(dates[i]) for i in idx]
    last_full = (series.dates[-1].year - 1) if series.dates else dt.date.today().year - 1
    first = max(config.CLIMATOLOGY_START, series.dates[0].year if series.dates else 1995)

    days = []
    for i, d in enumerate(dates):
        tx, tn = members["temperature_2m_max"][i], members["temperature_2m_min"][i]
        pr = members["precipitation_sum"][i]
        if not any(v is not None for v in tx):
            continue
        n = sum(1 for v in tx if v is not None) or 1
        days.append({
            "date": d, "in_window": i in idx,
            "tmax": {"p10": _pct(tx, 10), "p50": _pct(tx, 50), "p90": _pct(tx, 90)},
            "tmin": {"p50": _pct(tn, 50)},
            "precip": {"p50": _pct(pr, 50), "p90": _pct(pr, 90)},
            "prob": {ev["key"]: round(sum(1 for v in members[ev["var"]][i]
                                          if _hit(v, ev["op"], ev["threshold"])) / n, 2)
                     for ev in EVENTS},
        })

    events = []
    for ev in EVENTS:
        f = forecast_event(members, idx, ev)
        if f is None:
            continue
        c = climatology_event(series, window, ev, first, last_full)
        events.append({"key": ev["key"], "label": ev["label"], "threshold": ev["threshold"],
                       "forecast": f, "climatology": c, "signal": signal(f, c)})

    span = (f"{_fmt_date(dates[idx[0]])} to {_fmt_date(dates[idx[-1]])}" if idx else None)
    # The event that departs MOST from the usual leads, not the most likely one.
    unusual = sorted((e for e in events if e["signal"] == ABOVE),
                     key=lambda e: -(e["forecast"]["prob_any"] - e["climatology"]["prob_any"]))
    if not idx:
        headline = ("The dates fall outside the forecast horizon (the next 15 days): "
                    "for them only the usual climate applies for now")
    elif unusual:
        top = unusual[0]
        short = next(ev["short"] for ev in EVENTS if ev["key"] == top["key"])
        clim = top["climatology"]
        headline = (f"{span}: {top['forecast']['prob_any'] * 100:.0f} % chance of "
                    f"{short}, when the usual for these dates is "
                    f"{clim['prob_any'] * 100:.0f} %")
    else:
        headline = f"{span}: nothing out of the ordinary for these dates"

    return {
        "provider": fc["provider"], "provenance": fc["provenance"], "licence": fc["licence"],
        "grid": fc.get("grid"), "dates": [dates[0], dates[-1]] if dates else None,
        "window": span, "trip": [trip[0].isoformat(), trip[1].isoformat()] if trip else None,
        "headline": headline, "events": events, "days": days,
        "members": events[0]["forecast"]["members"] if events else None,
        "limitation": ("It is a forecast, not a risk, and it does not count towards the score. "
                       "The probability is the share of the model's ensemble members in which "
                       "the event happens; beyond 7-10 days reliability drops sharply. The "
                       "~28 km grid cannot see local storms. \"Usual\" comes from the ERA5 "
                       "record (~9 km) on the same dates: different sources and resolutions, so "
                       "compare orders of magnitude, not decimals."),
    }
