"""What stands inside a polygon · TALAIA. Needs an API key.

The cadastre says a building is there, when it was raised, what it is used for and how
many dwellings it holds. It does not say that the building is a care home, how many
people sleep in it, or what it would cost to replace. TALAIA does: give it an area and
it returns the schools, hospitals, care homes, farms and livestock, campsites, industry
and hazardous sites inside it, with capacity, a replacement valuation and the census
population of the ground.

That is an answer about an AREA, which is why it has no place in a report - a resident
does not act differently because there are two schools down the road - and every place
in `/analisis`, whose whole question is which homes and which people an area threatens.
It is called in batch by `backend/scripts/analysis_build.py`, never on a request.

It never scores. Like the fire detections and the alerts, it is context: the flood score
of a municipality comes from the official zones and the buildings standing in them, and
nothing here changes it.

Credentials: `TALAIA_API_KEY` (self-service at /v1/signup, confirmed by email).
Without it `available()` is False, the analysis is built exactly as before and each
municipality says the inventory was not asked for rather than that there is nothing
there.

The free tier allows an area of 250 km2 and 2,000 assets per call, which is why the
caller sends the bounding box of the exposed buildings rather than of the whole
municipality: it is both smaller and the only part anybody is going to act on.
"""

from __future__ import annotations

import httpx

from .. import cache, config

TIMEOUT = 120.0
# The inventory of a town changes on the cadence of its sources (annual registers, OSM):
# a month is the same window the climatology uses.
TTL = 30 * 24 * 3600

# What the caller wants and what it means here. The keys are TALAIA's own categories;
# `/v1/taxonomy` is the live list and this is only the labelling used by the analysis.
HUMAN_CATEGORIES = ("education", "health", "social", "accommodation", "population")


def available() -> bool:
    return bool(config.TALAIA_KEY)


def _headers() -> dict:
    return {"X-API-Key": config.TALAIA_KEY or "",
            "User-Agent": config.USER_AGENT,
            "Content-Type": "application/json"}


def bbox_polygon(bbox: list[float] | tuple[float, ...]) -> dict:
    """(west, south, east, north) -> a GeoJSON Polygon, the AOI TALAIA takes."""
    w, s, e, n = bbox
    return {"type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


async def exposure(aoi: dict, *, layers: list[str] | None = None, buffer_m: float = 0,
                   max_assets: int = 2000, cache_key: str | None = None) -> dict:
    """Everything of value inside the AOI, with its people and its replacement cost.

    Returns TALAIA's report as it comes, plus `ok`. A refusal (no key, area over the
    tier's limit, quota spent) is returned as `{"ok": False, "error": ...}` and never
    raised: a municipality without an inventory is a municipality without an inventory,
    not a failed build.
    """
    if not available():
        return {"ok": False, "error": "no TALAIA_API_KEY configured"}

    if cache_key:
        hit = cache.get("talaia", cache_key, ttl=TTL)
        if hit is not None:
            return {**hit, "ok": True, "from_cache": True}

    body = {
        "aoi": aoi,
        "include_assets": True,
        "include_population": True,
        "include_networks": False,
        "include_geometry": False,
        "conflate": True,
        "max_assets": max_assets,
        "sort_by": "priority",
    }
    if layers:
        body["layers"] = layers
    if buffer_m:
        body["buffer_m"] = buffer_m

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{config.TALAIA_URL}/v1/exposure",
                                     json=body, headers=_headers())
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if resp.status_code != 200:
        detail = ""
        try:
            detail = str((resp.json() or {}).get("detail") or "")[:300]
        except ValueError:
            detail = resp.text[:300]
        return {"ok": False, "status": resp.status_code,
                "error": detail or f"TALAIA answered {resp.status_code}"}

    payload = resp.json()
    if cache_key:
        cache.set("talaia", cache_key, payload)
    return {**payload, "ok": True, "from_cache": False}


async def tiers() -> dict:
    """The published tiers and their limits. No key needed; used to explain a refusal."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{config.TALAIA_URL}/v1/tiers")
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


async def whoami() -> dict:
    """What the configured key is allowed to do, or why it is not usable."""
    if not available():
        return {"ok": False, "error": "no TALAIA_API_KEY configured"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{config.TALAIA_URL}/v1/me", headers=_headers())
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if resp.status_code != 200:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:200]}
    return {**resp.json(), "ok": True}


def status() -> dict:
    return {"configured": available(), "url": config.TALAIA_URL}
