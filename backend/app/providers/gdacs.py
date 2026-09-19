"""Ongoing alerts · GDACS (United Nations and European Commission). Worldwide, no key.

It does not score: a hazard report talks about long-term probabilities and an alert
talks about today. Mixing them would make the same address change its score depending
on the day.

The EVENTS4APP feed carries the ~100 current events with one point per event. Whether
they affect the place is decided with a radius per type: a flood covers hundreds of
kilometres and a wildfire does not.
"""

from __future__ import annotations

import httpx

from .. import cache, config
from ..geo import haversine_km

FEED_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
TTL_S = 30 * 60  # half an hour: these are alerts, not climatology

# Only the alert types in scope (GDACS has no heatwave or avalanche alerts).
TYPE_EN = {"FL": "Flood", "WF": "Wildfire"}
ALERT_EN = {"Green": "green", "Orange": "orange", "Red": "red"}
RADIUS_KM = {"FL": 300, "WF": 60}


def _severity(props: dict) -> str | None:
    data = props.get("severitydata") or {}
    text = (data.get("severitytext") or "").strip()
    return text if text and data.get("severity") not in (0, 0.0, None) else None


def relevant(features: list[dict], lat: float, lon: float) -> list[dict]:
    out = []
    for f in features:
        p = f.get("properties", {})
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if str(p.get("iscurrent", "")).lower() != "true" or len(coords) < 2:
            continue
        kind, level = p.get("eventtype"), p.get("alertlevel")
        if kind not in RADIUS_KM:
            continue
        radius = RADIUS_KM[kind]
        d = haversine_km(lat, lon, coords[1], coords[0])
        if d > radius:
            continue
        out.append({
            "type": kind, "type_label": TYPE_EN.get(kind, kind), "name": p.get("name"),
            "alert": level, "alert_label": ALERT_EN.get(level, level),
            # Floods arrive with "Magnitude 0": filler, not data.
            "severity": _severity(p),
            "from": p.get("fromdate"), "to": p.get("todate"), "country": p.get("country"),
            "distance_km": round(d), "radius_km": radius,
            "url": (p.get("url") or {}).get("report"),
        })
    order = {"Red": 0, "Orange": 1, "Green": 2}
    return sorted(out, key=lambda a: (order.get(a["alert"], 3), a["distance_km"]))


async def current_alerts(lat: float, lon: float) -> dict:
    feed = cache.get("gdacs", "events4app", ttl=TTL_S)
    if feed is None:
        try:
            async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                         headers={"User-Agent": config.USER_AGENT}) as client:
                resp = await client.get(FEED_URL)
            resp.raise_for_status()
            feed = resp.json()
            cache.set("gdacs", "events4app", feed)
        except (httpx.HTTPError, ValueError):
            feed = cache.get("gdacs", "events4app", allow_stale=True)
            if feed is None:
                raise
    features = feed.get("features", [])
    return {"alerts": relevant(features, lat, lon), "checked": len(features),
            "source": "GDACS", "url": "https://www.gdacs.org/"}
