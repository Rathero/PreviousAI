"""Slopes around the point · Copernicus DEM (90 m) via the Open-Meteo Elevation API.

It answers one question: is there avalanche terrain here? Avalanches start on slopes of
roughly 30-50 degrees; below 30 they rarely release, above 50 snow rarely builds up.
Outside the Catalan Pyrenees (where ICGC maps the avalanche paths) this and the
snowfall record are the only avalanche information.

A single request with 81 points: the centre and 16 rays sampled at 125, 250, 500, 750
and 1,000 m (avalanches run out far below where they start). A 90 m DEM smooths the
terrain, so real slopes are steeper than these: the value is a lower bound.
"""

from __future__ import annotations

import asyncio
import math

import httpx

from .. import cache, config

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
RADII_M = (125, 250, 500, 750, 1000)
RAYS = 16
# Avalanches release on 30-55° slopes. On a 90 m model steep slopes come out a few
# degrees gentler (a ski base ringed by avalanche slopes can measure 29°), so 28° on
# this model is the threshold.
AVALANCHE_MIN_DEG = 28
# Below this height difference within 1 km the ground is flat.
FLAT_RELIEF_M = 30


def sample_points(lat: float, lon: float) -> list[tuple[float, float]]:
    m_lat = 111_200
    m_lon = 111_200 * max(math.cos(math.radians(lat)), 0.05)
    pts = [(lat, lon)]
    for k in range(RAYS):
        a = math.radians(360 / RAYS * k)
        for r in RADII_M:
            pts.append((round(lat + r * math.cos(a) / m_lat, 5), round(lon + r * math.sin(a) / m_lon, 5)))
    return pts


def summarize(elevations: list[float | None]) -> dict | None:
    """Slopes along each ray, from the centre outwards."""
    if len(elevations) != 1 + RAYS * len(RADII_M) or elevations[0] is None:
        return None
    center = elevations[0]
    slopes = []
    for k in range(RAYS):
        ray = [center] + elevations[1 + k * len(RADII_M): 1 + (k + 1) * len(RADII_M)]
        dists = (0,) + RADII_M
        for i in range(len(RADII_M)):
            if ray[i] is None or ray[i + 1] is None:
                continue
            run = dists[i + 1] - dists[i]
            slopes.append(math.degrees(math.atan(abs(ray[i + 1] - ray[i]) / run)))
    vals = [e for e in elevations if e is not None]
    if not slopes:
        return None
    steep = [s for s in slopes if AVALANCHE_MIN_DEG <= s <= 55]
    return {
        "center_m": center, "relief_m": round(max(vals) - min(vals)),
        "max_slope_deg": round(max(slopes), 1),
        "steep_share": round(len(steep) / len(slopes), 2),
        "radius_m": RADII_M[-1], "points": len(elevations),
        "flat": max(vals) - min(vals) < FLAT_RELIEF_M,
    }


async def profile(lat: float, lon: float) -> dict | None:
    key = f"profile:v2:{lat:.4f},{lon:.4f}"
    hit = cache.get("terrain", key)
    if hit is not None:
        return hit
    pts = sample_points(lat, lon)
    params = {"latitude": ",".join(str(p[0]) for p in pts),
              "longitude": ",".join(str(p[1]) for p in pts)}
    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        resp = await client.get(ELEVATION_URL, params=params)
        if resp.status_code >= 500:  # a passing 5xx: one retry
            await asyncio.sleep(1.0)
            resp = await client.get(ELEVATION_URL, params=params)
    resp.raise_for_status()
    result = summarize(resp.json().get("elevation") or [])
    if result:
        cache.set("terrain", key, result)
    return result
