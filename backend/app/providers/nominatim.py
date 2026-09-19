"""Nominatim (OpenStreetMap): forward and reverse geocoding, worldwide.

ThinkHazard! uses it (which province is this point in) and so does the address search
outside Spain. Its usage policy requires identification and at most one request per
second: one lock is shared by the whole process, and everything is cached.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from .. import cache, config

BASE_URL = "https://nominatim.openstreetmap.org"
_LOCK = asyncio.Lock()
_last_call = 0.0


async def _get(path: str, params: dict, cache_key: str):
    global _last_call
    hit = cache.get("nominatim", cache_key)
    if hit is not None:
        return hit
    async with _LOCK:
        hit = cache.get("nominatim", cache_key)  # another task may have fetched it meanwhile
        if hit is not None:
            return hit
        wait = 1.1 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                         headers={"User-Agent": config.USER_AGENT}) as client:
                resp = await client.get(f"{BASE_URL}/{path}", params=params)
            resp.raise_for_status()
            data = resp.json()
        finally:
            _last_call = time.monotonic()
    cache.set("nominatim", cache_key, data)
    return data


async def reverse(lat: float, lon: float, *, zoom: int = 8) -> dict:
    """Administrative address of the point, in English (to match ThinkHazard!).

    Zoom 8 and three decimals: coarser settings can drop a delta or coastal point in
    the sea and return only the country."""
    params = {"lat": round(lat, 3), "lon": round(lon, 3), "format": "jsonv2",
              "zoom": zoom, "accept-language": "en"}
    data = await _get("reverse", params, f"rev{zoom}:{lat:.3f},{lon:.3f}")
    return data.get("address", {})


async def search(query: str) -> dict | None:
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1,
              "accept-language": "en"}
    data = await _get("search", params, f"search:en:{query}")
    return data[0] if data else None


def to_place(hit: dict) -> dict:
    """Nominatim result -> report place, with its real precision."""
    addr = hit.get("address") or {}
    if addr.get("house_number"):
        precision = "address"
    elif addr.get("road") or addr.get("pedestrian") or addr.get("square"):
        precision = "street"
    elif hit.get("addresstype") in ("city", "town", "village", "municipality", "suburb"):
        precision = "town"
    else:
        precision = "place"
    town = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
    street = " ".join(x for x in (addr.get("road"), addr.get("house_number")) if x)
    label = ", ".join(x for x in (street, town, addr.get("country")) if x) or hit.get("display_name")
    return {
        "name": street or town or hit.get("name") or label,
        "label": label,
        "latitude": float(hit["lat"]), "longitude": float(hit["lon"]),
        "country": addr.get("country"), "country_code": (addr.get("country_code") or "").upper() or None,
        "admin1": addr.get("state"), "admin2": addr.get("province") or addr.get("county"),
        "town": town,
        "timezone": None, "elevation": None,
        "precision": precision, "geocoder": "Nominatim (OpenStreetMap)",
    }
