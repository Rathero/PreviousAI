"""Satellite-detected fires and fire-spread simulations · Deepfire. Needs an API client.

Deepfire groups satellite hotspots (VIIRS, MODIS, Sentinel-3, Landsat and the
geostationary MTG, which images Europe every 10 minutes) into candidate fires,
worldwide, since January 2025, and masks known static heat sources (flares, solar farms,
industry). It is used three ways, and none of them scores:

  - right now: fires active within 50 km of the point, next to the other "today" data;
  - recent record: fires detected within 10 km since January 2025, as context on the
    wildfire card and in the history of the place;
  - on request: a fire-spread simulation (ELMFIRE) from the nearest risky land with the
    current weather. A what-if, labelled as such.

Credentials: DEEPFIRE_CLIENT_ID and DEEPFIRE_CLIENT_SECRET (app.deepfire.co -> Settings
-> API clients), exchanged once per process for a bearer token. Without them nothing is
queried and nothing else changes.

Each satellite family seeds its own cluster, so the same fire often arrives as one MTG
cluster and one VIIRS/MODIS cluster a kilometre or two apart. Clusters whose time
windows overlap (12 h of slack) and whose detections lie within 2 km are merged into one
fire here. An isolated single detection without high confidence is often not a fire:
those are counted apart, not listed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import os
import time

import httpx

from .. import cache, config
from ..geo import haversine_km

API = "https://api.deepfire.co"
TOKEN_URL = f"{API}/v1/token"
ITEMS_URL = f"{API}/ogc/features/v1/collections/{{collection}}/items"
SPREAD_URL = f"{API}/v1/fire-spread/simulations"
APP_URL = "https://app.deepfire.co/"
DOCS_URL = "https://docs.deepfire.co/"
HISTORY_START = "2025-01-01"   # Deepfire's full history begins in January 2025

NOW_RADIUS_KM = 50
NOW_TTL_S = 10 * 60
RECORD_RADIUS_KM = 10
RECORD_TTL_S = 6 * 3600
MERGE_KM = 2.0
MERGE_SLACK_H = 12
SPREAD_HOURS = 6
MAX_LIMIT = 10_000             # the API clamps pages at 10,000 features

_token: dict = {}


def credentials() -> tuple[str | None, str | None]:
    return os.getenv("DEEPFIRE_CLIENT_ID"), os.getenv("DEEPFIRE_CLIENT_SECRET")


def available() -> bool:
    return all(credentials())


async def _bearer(client: httpx.AsyncClient) -> str:
    if _token.get("value") and _token.get("expires", 0) > time.time() + 60:
        return _token["value"]
    cid, secret = credentials()
    resp = await client.post(TOKEN_URL, json={"client_id": cid, "client_secret": secret})
    resp.raise_for_status()
    body = resp.json()
    _token.update(value=body["access_token"], expires=time.time() + float(body.get("expires_in", 3600)))
    return _token["value"]


async def _request(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """Authenticated call. A 503 means the shared concurrency cap: one polite retry after
    Retry-After. A 401 means a stale token: exchange again once."""
    for attempt in range(2):
        headers = {"Authorization": f"Bearer {await _bearer(client)}"}
        resp = await client.request(method, url, headers=headers, **kw)
        if resp.status_code == 401 and attempt == 0:
            _token.clear()
            continue
        if resp.status_code == 503 and attempt == 0:
            await asyncio.sleep(min(float(resp.headers.get("Retry-After", "2") or 2), 5))
            continue
        break
    resp.raise_for_status()
    return resp


async def _items(client, collection: str, bbox: tuple[float, float, float, float],
                 cql: str | None = None) -> list[dict]:
    params = {"bbox": ",".join(f"{v:.5f}" for v in bbox), "f": "application/geo+json",
              "limit": MAX_LIMIT}
    if cql:
        params.update({"filter-lang": "cql2-text", "filter": cql})
    resp = await _request(client, "GET", ITEMS_URL.format(collection=collection), params=params)
    return resp.json().get("features", [])


def bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    d_lat = radius_km / 111.2
    d_lon = radius_km / (111.2 * max(math.cos(math.radians(lat)), 0.05))
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def _time(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _rings(geometry: dict | None) -> list[list[list[float]]]:
    """GeoJSON (Multi)Polygon -> [[[lat, lon], ...] per ring]."""
    if not geometry:
        return []
    polys = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        polys = [polys]
    return [[[round(p[1], 5), round(p[0], 5)] for p in ring] for poly in polys for ring in poly[:1]]


def build_fires(clusters: list[dict], hotspots: list[dict], perimeters: list[dict],
                lat: float, lon: float, radius_km: float) -> tuple[list[dict], int]:
    """Merged fires within `radius_km` of the point, newest first, and how many isolated
    low-confidence single detections were left out."""
    spots: dict[str, list[dict]] = {}
    for h in hotspots:
        p = h.get("properties") or {}
        coords = (h.get("geometry") or {}).get("coordinates") or []
        if p.get("cluster_id") and len(coords) >= 2:
            spots.setdefault(p["cluster_id"], []).append(
                {"lat": coords[1], "lon": coords[0], "at": p.get("observed_at"),
                 "source": p.get("source"), "confidence": p.get("confidence"),
                 "frp": p.get("fire_radiative_power")})
    latest_perimeter: dict[str, dict] = {}
    for f in perimeters:
        p = f.get("properties") or {}
        cid = p.get("cluster_id")
        if cid and (cid not in latest_perimeter or
                    (p.get("computed_at") or "") > latest_perimeter[cid]["properties"].get("computed_at", "")):
            latest_perimeter[cid] = f

    groups = []
    for c in clusters:
        p = c.get("properties") or {}
        coords = (c.get("geometry") or {}).get("coordinates") or []
        pts = spots.get(p.get("id"), [])
        if not pts and len(coords) >= 2:
            pts = [{"lat": coords[1], "lon": coords[0], "at": p.get("first_observed"),
                    "source": None, "confidence": None, "frp": None}]
        if not pts:
            continue
        groups.append({"ids": [p.get("id")], "points": pts, "active": bool(p.get("active")),
                       "first": _time(p.get("first_observed")), "last": _time(p.get("last_observed"))})

    # Merge the same fire seen by different satellite families.
    slack = dt.timedelta(hours=MERGE_SLACK_H)
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = groups[i], groups[j]
                if None in (a["first"], a["last"], b["first"], b["last"]):
                    continue
                if a["first"] - slack > b["last"] or b["first"] - slack > a["last"]:
                    continue
                if min(haversine_km(p["lat"], p["lon"], q["lat"], q["lon"])
                       for p in a["points"] for q in b["points"]) > MERGE_KM:
                    continue
                a["ids"] += b["ids"]
                a["points"] += b["points"]
                a["active"] = a["active"] or b["active"]
                a["first"], a["last"] = min(a["first"], b["first"]), max(a["last"], b["last"])
                del groups[j]
                merged = True
                break
            if merged:
                break

    fires, singles = [], 0
    for g in groups:
        pts = g["points"]
        dist = min(haversine_km(lat, lon, p["lat"], p["lon"]) for p in pts)
        if dist > radius_km:
            continue
        confidences = {p["confidence"] for p in pts if p["confidence"]}
        if len(pts) == 1 and "HIGH" not in confidences:
            singles += 1
            continue
        perims = [latest_perimeter[i] for i in g["ids"] if i in latest_perimeter]
        best = max(perims, key=lambda f: f["properties"].get("area_m2") or 0) if perims else None
        area = (best["properties"].get("area_m2") or 0) / 1e4 if best else None
        frps = [p["frp"] for p in pts if p["frp"] is not None]
        near = min(pts, key=lambda p: haversine_km(lat, lon, p["lat"], p["lon"]))
        fires.append({
            "first": g["first"].isoformat() if g["first"] else None,
            "last": g["last"].isoformat() if g["last"] else None,
            "active": g["active"],
            "distance_km": round(dist, 1),
            "lat": round(near["lat"], 5), "lon": round(near["lon"], 5),
            "detections": len(pts),
            "max_frp_mw": round(max(frps), 1) if frps else None,
            "confidence": "high" if "HIGH" in confidences else
                          "medium" if "MEDIUM" in confidences else "low",
            "sources": sorted({p["source"] for p in pts if p["source"]}),
            "area_ha": round(area, 1) if area else None,
            "perimeter": _rings(best.get("geometry")) if best else [],
            "cluster_ids": g["ids"],
        })
    fires.sort(key=lambda f: f["last"] or "", reverse=True)
    return fires, singles


async def _fires(lat: float, lon: float, radius_km: float, cql: str | None) -> tuple[list[dict], int]:
    box = bbox_around(lat, lon, radius_km + MERGE_KM)
    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        clusters = await _items(client, "deepfire:clusters", box, cql)
        if not clusters:
            return [], 0
        # Serial, not a fan-out: the API shares one concurrency cap among all callers.
        hotspots = await _items(client, "deepfire:hotspots", box, cql)
        perimeters = await _items(client, "deepfire:satellite-perimeters", box, cql)
    return build_fires(clusters, hotspots, perimeters, lat, lon, radius_km)


async def _cached(kind: str, lat: float, lon: float, ttl: float, fetch) -> dict:
    key = f"{kind}:{lat:.4f},{lon:.4f}"
    hit = cache.get("deepfire", key, ttl=ttl)
    if hit is not None:
        return hit
    try:
        value = await fetch()
    except (httpx.HTTPError, ValueError, KeyError):
        stale = cache.get("deepfire", key, allow_stale=True)
        if stale is None:
            raise
        return {**stale, "stale": True}
    cache.set("deepfire", key, value)
    return value


async def active_near(lat: float, lon: float) -> dict | None:
    """Fires burning now (a detection in the last 24 h) within 50 km."""
    if not available():
        return None

    async def fetch():
        fires, _ = await _fires(lat, lon, NOW_RADIUS_KM, "active = true")
        return {"fires": [{k: v for k, v in f.items() if k != "perimeter"} | {"perimeter": f["perimeter"]}
                          for f in fires[:8]],
                "count": len(fires), "radius_km": NOW_RADIUS_KM,
                "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                "source": "Deepfire", "url": APP_URL}
    return await _cached("now", lat, lon, NOW_TTL_S, fetch)


async def record_near(lat: float, lon: float) -> dict | None:
    """Fires detected by satellite within 10 km since January 2025."""
    if not available():
        return None

    async def fetch():
        fires, singles = await _fires(lat, lon, RECORD_RADIUS_KM, None)
        return {"fires": fires, "count": len(fires), "singles_left_out": singles,
                "radius_km": RECORD_RADIUS_KM, "since": HISTORY_START,
                "until": dt.date.today().isoformat(), "source": "Deepfire", "url": APP_URL}
    return await _cached("record", lat, lon, RECORD_TTL_S, fetch)


# --------------------------------------------------------------------------- #
# Fire-spread simulations (on request)
# --------------------------------------------------------------------------- #
def summarize_spread(sim: dict, lat: float | None = None, lon: float | None = None) -> dict:
    """Hour-by-hour burnt area and outlines, and how close the fire came to the analysed
    point. The polygons are Deepfire's; the areas are measured here."""
    from ..geo import polygon_area, utm_forward

    out = {k: sim.get(k) for k in ("id", "status", "model", "durationHours", "ensembleMembers",
                                   "latitude", "longitude", "locationName", "createdAt",
                                   "errorMessage")}
    summary = sim.get("summary") or {}
    out["wind_speed_ms"] = summary.get("windSpeedAvgMs")
    out["wind_from_deg"] = summary.get("windDirectionAvg")
    out["burned_ha"] = round(summary["burnedAreaM2"] / 1e4, 2) if summary.get("burnedAreaM2") else None
    out["edge_reached"] = summary.get("edgeReached")
    hours = []
    for f in (sim.get("result") or {}).get("features", []):
        geom = f.get("geometry") or {}
        polys = geom.get("coordinates") or []
        if geom.get("type") == "Polygon":
            polys = [polys]
        area = sum(polygon_area([[utm_forward(p[1], p[0]) for p in ring] for ring in poly])
                   for poly in polys) / 1e4
        closest = None
        if lat is not None:
            closest = min((haversine_km(lat, lon, p[1], p[0]) * 1000
                           for poly in polys for ring in poly for p in ring), default=None)
        hours.append({"hour": (f.get("properties") or {}).get("hour"),
                      "area_ha": round(area, 2),
                      "closest_m": None if closest is None else round(closest),
                      "rings": [[[round(p[1], 5), round(p[0], 5)] for p in ring]
                                for poly in polys for ring in poly[:1]]})
    out["hours"] = hours
    return out


async def start_spread(lat: float, lon: float, hours: int = SPREAD_HOURS) -> dict:
    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        resp = await _request(client, "POST", SPREAD_URL, json={
            "latitude": round(lat, 5), "longitude": round(lon, 5), "durationHours": int(hours)})
    return resp.json()


async def get_spread(sim_id: str) -> dict:
    """A simulation by id. Finished runs are cached for good: they do not change."""
    hit = cache.get("deepfire_spread", sim_id, allow_stale=True)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        resp = await _request(client, "GET", f"{SPREAD_URL}/{sim_id}")
    sim = resp.json()
    if sim.get("status") in ("COMPLETED", "NO_SPREAD", "FAILED"):
        cache.set("deepfire_spread", sim_id, sim)
    return sim
