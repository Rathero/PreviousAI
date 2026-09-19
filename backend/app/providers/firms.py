"""Active fire hotspots · NASA FIRMS (VIIRS). Optional: it needs a free MAP_KEY.

Switched on only with FIRMS_MAP_KEY (https://firms.modaps.eosdis.nasa.gov/api/map_key/).
It is a "right now" layer, like the GDACS alerts, and it does not score.
"""

from __future__ import annotations

import csv
import io

import httpx

from .. import cache, config
from ..geo import haversine_km

AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}"
SOURCE = "VIIRS_SNPP_NRT"
TTL_S = 30 * 60


def api_key() -> str | None:
    return config.FIRMS_KEY


def parse_hotspots(text: str, lat: float, lon: float, radius_km: float) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text or "")):
        try:
            la, lo = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        d = haversine_km(lat, lon, la, lo)
        if d > radius_km:
            continue
        out.append({"distance_km": round(d, 1), "date": row.get("acq_date"),
                    "time": row.get("acq_time"), "confidence": row.get("confidence"),
                    "frp_mw": float(row["frp"]) if row.get("frp") else None})
    return sorted(out, key=lambda h: h["distance_km"])


async def hotspots_near(lat: float, lon: float, radius_km: float = 50, days: int = 2) -> dict | None:
    key = api_key()
    if not key:
        return None
    d = radius_km / 111.2 * 1.5
    bbox = f"{lon - d:.3f},{lat - d:.3f},{lon + d:.3f},{lat + d:.3f}"
    ckey = f"{bbox}|{days}"
    text = cache.get("firms", ckey, ttl=TTL_S)
    if text is None:
        async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT) as client:
            resp = await client.get(AREA_URL.format(key=key, source=SOURCE, bbox=bbox, days=days))
        resp.raise_for_status()
        text = resp.text
        cache.set("firms", ckey, text)
    spots = parse_hotspots(text, lat, lon, radius_km)
    return {"count": len(spots), "nearest": spots[:5], "radius_km": radius_km, "days": days,
            "source": "NASA FIRMS (VIIRS S-NPP, near real time)"}
