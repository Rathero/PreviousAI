"""What has already happened near the home: the incidents on record, newest first.

Floods that affected the municipality (AGORA, 1902-2020), wildfires with a mapped
perimeter within 5 km (Government of Catalonia, 1986-2024), fires seen by satellite
within 10 km (Deepfire, since 2025) and avalanches observed within 1 km (ICGC), plus the
hottest and wettest days of the ERA5 climate record. Every row names its source; none
of them changes a score beyond the cards they already feed.
"""

from __future__ import annotations

from .providers.catalonia_store import parse_losses

MAX_PER_KIND = 6


def _distance(metres: float | None) -> str:
    if metres is None:
        return ""
    return f"{metres:.0f} m away" if metres < 1000 else f"{metres / 1000:.1f} km away"


def _eur(value: float | None) -> str | None:
    if not value:
        return None
    return f"€{value / 1e6:,.1f} M" if value >= 1e6 else f"€{value:,.0f}"


def _indicator(report: dict, card: str, key: str) -> dict | None:
    h = next((h for h in report.get("hazards", []) if h["key"] == card), None)
    return next((i for i in (h or {}).get("indicators", []) if i["key"] == key), None)


def build(report: dict) -> dict:
    events = report.get("events") or {}
    items: list[dict] = []

    for e in (events.get("flood_episodes") or [])[:MAX_PER_KIND]:
        parts = []
        if str(e.get("category") or "").strip():
            parts.append(f"severity category {e['category']}")
        victims = str(e.get("victims") or "").strip()
        if victims.isdigit() and int(victims) > 0:
            parts.append(f"{victims} victim{'s' if int(victims) > 1 else ''} across the episode")
        losses = _eur(e.get("losses_eur") or parse_losses(e.get("losses_raw")))
        if losses:
            parts.append(f"{losses} in losses across the episode")
        items.append({"date": e.get("date"), "family": "flood", "kind": "flood_episode",
                      "title": "Flood episode in the municipality",
                      "detail": " · ".join(parts) or None,
                      "source": "AGORA · University of Barcelona", "url": e.get("report_url")})

    fires = sorted(events.get("nearby_fires") or [], key=lambda f: f.get("date") or str(f.get("year")),
                   reverse=True)
    for f in fires[:MAX_PER_KIND]:
        where = "it reached this point" if f.get("inside") else _distance(f.get("distance_m"))
        muni = f.get("municipality")
        items.append({"date": f.get("date") or str(f.get("year")), "family": "wildfire",
                      "kind": "mapped_fire",
                      "title": f"Wildfire of {f['area_ha']:,.0f} ha" if f.get("area_ha") else "Wildfire",
                      "detail": " · ".join(x for x in (where, muni) if x) or None,
                      "source": "Government of Catalonia · wildfire perimeters"})

    for f in (events.get("satellite_fires") or [])[:MAX_PER_KIND]:
        bits = [f"{f['distance_km']:.1f} km away",
                f"{f['detections']} satellite detection{'s' if f['detections'] != 1 else ''}"]
        if f.get("area_ha"):
            bits.append(f"~{f['area_ha']:,.0f} ha")
        items.append({"date": (f.get("first") or "")[:10] or None, "family": "wildfire",
                      "kind": "satellite_fire",
                      "title": "Fire detected by satellite", "detail": " · ".join(bits),
                      "source": "Deepfire (satellite detections; can include farm burns)"})

    avalanches = sorted(events.get("avalanches") or [], key=lambda a: a.get("year") or 0, reverse=True)
    for a in avalanches[:MAX_PER_KIND]:
        items.append({"date": str(a["year"]) if a.get("year") else None, "family": "avalanche",
                      "kind": "avalanche",
                      "title": "Avalanche observed",
                      "detail": "it reached this point" if a.get("inside") else _distance(a.get("distance_m")),
                      "source": "ICGC · Catalan avalanche database"})

    since = ((report.get("window") or {}).get("full_record") or "").split("-")[0] or "1979"
    hottest = (events.get("hottest_days") or [None])[0]
    if hottest:
        items.append({"date": hottest["date"], "family": "heat", "kind": "hottest_day",
                      "title": f"Hottest day since {since}: {hottest['value']:.1f} °C",
                      "detail": "daily maximum over the ~9 km climate cell",
                      "source": "ERA5 reanalysis (Copernicus)"})
    wettest = (events.get("wettest_days") or [None])[0]
    if wettest:
        items.append({"date": wettest["date"], "family": "flood", "kind": "wettest_day",
                      "title": f"Wettest day since {since}: {wettest['value']:.0f} mm of rain",
                      "detail": "daily total over the ~9 km climate cell",
                      "source": "ERA5 reanalysis (Copernicus)"})

    items.sort(key=lambda i: i.get("date") or "", reverse=True)

    summary = []
    n = _indicator(report, "flood_history", "flood_episodes")
    if n and n.get("value"):
        summary.append(f"{n['value']:.0f} flood episodes in the municipality since "
                       f"{str(n['provenance']['period'])[:4]}")
    n = _indicator(report, "fire_history", "fires_5km")
    if n and n.get("value"):
        summary.append(f"{n['value']:.0f} mapped wildfires within 5 km since "
                       f"{str(n['provenance']['period'])[:4]}")
    n = _indicator(report, "avalanche", "avalanche_observed")
    if n and n.get("value"):
        summary.append(f"{n['value']:.0f} avalanches observed within 1 km")
    n = _indicator(report, "wildfire", "satellite_fires_10km")
    if n and n.get("value"):
        summary.append(f"{n['value']:.0f} fires seen by satellite within 10 km since 2025")

    catalonia = (report.get("coverage") or {}).get("region") == "Catalonia"
    note = None
    if not any(i["family"] in ("wildfire", "avalanche") or i["title"].startswith("Flood episode")
               for i in items):
        note = ("No floods, wildfires or avalanches are on record near this address in the official "
                "catalogues." if catalonia else
                "Official incident catalogues are available for Catalonia; here the history shows "
                "the extremes of the climate record.")
    return {"items": items, "summary": summary, "note": note}
