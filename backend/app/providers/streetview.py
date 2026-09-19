"""The home at street level · Google Street View Static API. Needs GOOGLE_MAPS_API_KEY.

Two calls: the metadata endpoint (free) says whether there is an outdoor panorama near
the address and where it was taken; the image endpoint returns the view from that
panorama, turned towards the address, so the picture faces the building rather than
whatever direction the car was driving.

Only the panorama's id, position and date are cached, as Google's terms allow. Images
are proxied on request and never stored. Without a key, or where Google has no
panorama, the web app shows the home from the air instead.
"""

from __future__ import annotations

import httpx

from .. import cache, config
from ..geo import bearing_deg, haversine_km

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"
SEARCH_RADIUS_M = 60
META_TTL_S = 30 * 24 * 3600
MAX_W, MAX_H = 640, 640   # the Static API's size limit


class StreetViewUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(config.GOOGLE_MAPS_KEY)


async def metadata(lat: float, lon: float) -> dict:
    """{"available", "pano_id", "lat", "lon", "date", "heading", "distance_m", "copyright"}."""
    if not available():
        return {"available": False, "reason": "no Google Maps key configured"}
    key = f"meta:{lat:.5f},{lon:.5f}:{SEARCH_RADIUS_M}"
    hit = cache.get("streetview", key, ttl=META_TTL_S)
    if hit is not None:
        return hit
    params = {"location": f"{lat},{lon}", "radius": SEARCH_RADIUS_M, "source": "outdoor",
              "key": config.GOOGLE_MAPS_KEY}
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": config.USER_AGENT}) as client:
            resp = await client.get(METADATA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise StreetViewUnavailable(f"Street View is not responding: {type(exc).__name__}") from exc
    status = data.get("status")
    if status != "OK":
        out = {"available": False,
               "reason": {"ZERO_RESULTS": "no Street View panorama near this address",
                          "NOT_FOUND": "no Street View panorama near this address",
                          "REQUEST_DENIED": "the Google Maps key was rejected (is the Street "
                                            "View Static API enabled for it?)",
                          "OVER_QUERY_LIMIT": "the Google Maps quota is exhausted"}
               .get(status, f"Street View answered {status}")}
        if status in ("ZERO_RESULTS", "NOT_FOUND"):
            cache.set("streetview", key, out)
        return out
    loc = data.get("location") or {}
    plat, plon = float(loc.get("lat", lat)), float(loc.get("lng", lon))
    out = {
        "available": True,
        "pano_id": data.get("pano_id"),
        "lat": plat, "lon": plon,
        "date": data.get("date"),
        "heading": round(bearing_deg(plat, plon, lat, lon), 1),
        "distance_m": round(haversine_km(plat, plon, lat, lon) * 1000),
        "copyright": data.get("copyright") or "© Google",
    }
    cache.set("streetview", key, out)
    return out


async def image(lat: float, lon: float, *, width: int = 640, height: int = 440) -> bytes:
    """The JPEG seen from the nearest panorama, facing the address."""
    meta = await metadata(lat, lon)
    if not meta.get("available"):
        raise StreetViewUnavailable(meta.get("reason") or "no panorama")
    close = (meta.get("distance_m") or 0) < 4  # standing on the point: any heading is a guess
    params = {"size": f"{min(width, MAX_W)}x{min(height, MAX_H)}", "pano": meta["pano_id"],
              "fov": 80 if not close else 100, "pitch": 6, "source": "outdoor",
              "return_error_code": "true", "key": config.GOOGLE_MAPS_KEY}
    if not close:
        params["heading"] = meta["heading"]
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": config.USER_AGENT}) as client:
            resp = await client.get(IMAGE_URL, params=params)
    except httpx.HTTPError as exc:
        raise StreetViewUnavailable(f"Street View is not responding: {type(exc).__name__}") from exc
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        raise StreetViewUnavailable(f"Street View image unavailable (HTTP {resp.status_code})")
    return resp.content
