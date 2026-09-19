"""What if a fire started on the nearest risky land today? Deepfire's ELMFIRE, on request.

The ignition is the nearest land FireScope rates at moderate risk or higher, within
3 km; without that, the analysed point itself. Deepfire runs ELMFIRE (a physics-based
fire-spread model) with its current weather for 6 hours and returns an outline per hour;
the burnt area and how close the fire came to the home are measured here.

It is a what-if, not a forecast of a real fire, and it never scores: the weather is
today's, the ignition is a choice, and one run is one possible outcome. One run per
ignition per day is kept (the terrain does not change, the weather does), which also
respects the API's limit of two runs in flight per client.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from . import cache
from .providers import deepfire, firescope

HOURS = deepfire.SPREAD_HOURS
DAY_TTL_S = 24 * 3600


def ignition(lat: float, lon: float, fs: dict | None) -> dict:
    """Where the what-if fire starts, and why there."""
    near = (fs or {}).get("nearest_at") or {}
    dist = (fs or {}).get("nearest_m") or {}
    for cls, label in (("moderate", "moderate or higher"), ("high", "high")):
        if near.get(cls):
            return {"lat": near[cls][0], "lon": near[cls][1], "distance_m": dist.get(cls),
                    "why": f"the nearest land FireScope rates at {label} risk"}
    return {"lat": round(lat, 5), "lon": round(lon, 5), "distance_m": 0,
            "why": "the analysed point (no land at moderate risk or higher within 3 km, "
                   "or FireScope does not cover it)"}


def _key(ign: dict) -> str:
    return f"{ign['lat']:.4f},{ign['lon']:.4f}:{HOURS}h:{dt.date.today().isoformat()}"


def view(sim: dict, lat: float, lon: float, ign: dict | None) -> dict:
    out = deepfire.summarize_spread(sim, lat, lon)
    out["ignition"] = ign
    last = out["hours"][-1] if out.get("hours") else None
    out["closest_m"] = min((h["closest_m"] for h in out.get("hours", []) if h["closest_m"] is not None),
                           default=None)
    out["final_area_ha"] = last["area_ha"] if last else None
    out["method"] = ("Deepfire fire-spread API, ELMFIRE model, 1 ensemble member, the provider's "
                     "current weather; outlines per hour from Deepfire, areas and distances "
                     "measured locally. A what-if: it does not score.")
    return out


async def _firescope(lat: float, lon: float) -> dict | None:
    if not firescope.raster_for(lat, lon):
        return None
    try:
        return await asyncio.to_thread(firescope.around, lat, lon)
    except Exception:  # noqa: BLE001 - without FireScope the point itself is the ignition
        return None


async def start(lat: float, lon: float) -> dict:
    """Starts today's run for this point, or returns the one already started."""
    ign = ignition(lat, lon, await _firescope(lat, lon))
    key = _key(ign)
    known = cache.get("fire_spread", key, ttl=DAY_TTL_S)
    if known:
        sim = await deepfire.get_spread(known["id"])
    else:
        sim = await deepfire.start_spread(ign["lat"], ign["lon"], HOURS)
        cache.set("fire_spread", key, {"id": sim["id"], "ignition": ign, "lat": lat, "lon": lon})
    return view(sim, lat, lon, ign)


async def status(sim_id: str, lat: float, lon: float) -> dict:
    sim = await deepfire.get_spread(sim_id)
    ign = None
    if sim.get("latitude") is not None:
        ign = {"lat": sim["latitude"], "lon": sim["longitude"]}
    return view(sim, lat, lon, ign)


def cached_view(lat: float, lon: float, fs: dict | None) -> dict | None:
    """Today's finished run for this point, if one exists. Never starts one: a report
    must not wait a minute for a what-if."""
    ign = ignition(lat, lon, fs)
    known = cache.get("fire_spread", _key(ign), ttl=DAY_TTL_S)
    if not known:
        return None
    sim = cache.get("deepfire_spread", known["id"], allow_stale=True)
    if not sim or sim.get("status") not in ("COMPLETED", "NO_SPREAD"):
        return None
    return view(sim, lat, lon, known.get("ignition") or ign)
