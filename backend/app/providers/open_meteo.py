"""Historical ERA5 and CMIP6 projections, over HTTP with no key (Open-Meteo).

These two APIs answer in seconds. The Climate Data Store serves the same ERA5 data
through a batch queue that takes minutes to hours, so it is never on the path of a
user request (see providers/cds.py).

Open-Meteo limits by VOLUME (days x variables), per minute, hour and day: one new point
costs roughly 1,800 of the 5,000 hourly calls. Everything here is built around that:
only variables that are used are requested, series are reused for 30 days, and a point
within 1 km and 50 m of height of a saved one reuses its series.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import httpx

from .. import cache, config

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"

# Daily variables the hazard engine uses. Minimum relative humidity is what allows a
# fire-danger proxy instead of a purely thermal one.
ARCHIVE_DAILY = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "relative_humidity_2m_min",
]

CLIMATE_DAILY = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
]

# Waits after a 429, in seconds. Their sum exceeds the one-minute window of the
# limiter: shorter waits land in the same minute again. The last entry marks the end.
RETRY_WAITS = (15.0, 30.0, 35.0, 0.0)


class UpstreamError(RuntimeError):
    pass


def archive_end_date() -> str:
    return (dt.date.today() - dt.timedelta(days=config.ARCHIVE_LAG_DAYS)).isoformat()


def _reason(resp) -> str:
    try:
        return str(resp.json().get("reason") or "")
    except ValueError:
        return ""


async def _get_with_retry(url: str, params: dict) -> dict:
    """GET with retries after a 429 on the per-minute limit.

    The hourly and daily limits are not fixed by waiting: those fail at once, so the
    saved series can be served instead.
    """
    last: Exception | None = None
    async with httpx.AsyncClient(
        timeout=config.HTTP_TIMEOUT, headers={"User-Agent": config.USER_AGENT}
    ) as client:
        for attempt, wait in enumerate(RETRY_WAITS):
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                reason = _reason(resp)
                last = UpstreamError(
                    "Open-Meteo request limit reached (429"
                    + (f": {reason}" if reason else "") + "). Saved places are still "
                    "served from the cache; new places can be analysed again shortly."
                )
                if any(w in reason.lower() for w in ("hourly", "daily")):
                    raise last
                if attempt < len(RETRY_WAITS) - 1:
                    retry_after = resp.headers.get("Retry-After")
                    await asyncio.sleep(
                        float(retry_after) if retry_after and retry_after.isdigit() else wait
                    )
                    continue
                raise last
            if resp.status_code >= 400:
                raise UpstreamError(f"{url} returned {resp.status_code}: {resp.text[:200]}")
            return resp.json()
    raise last or UpstreamError("request failed for no known reason")


NEARBY_KM = 5.0
_VARYING = {"latitude", "longitude", "end_date"}

# A second address in the same town asks for the same series: ERA5-Land cells are ~9 km
# and the height correction depends on the terrain, not the street. Within REUSE_KM and
# REUSE_DZ_M of a saved point, that series is reused (the report says so).
REUSE_KM = 1.0
REUSE_DZ_M = 50.0


def nearby_cached(namespace: str, url: str, params: dict, max_km: float = NEARBY_KM,
                  height: float | None = None, max_dz: float | None = None) -> dict | None:
    """Saved series for a point less than `max_km` away, with the same parameters.

    Last resort when Open-Meteo cuts us off. It is marked `_nearby` and the report says
    so. With `height`, only series whose grid height is within `max_dz` metres qualify.
    Series that are themselves reused copies never qualify: distances would chain.
    """
    import ast
    import json

    from ..geo import haversine_km

    wanted = {k: v for k, v in params.items() if k not in _VARYING}
    best = None
    for f in (config.CACHE_DIR / namespace).glob("*.json"):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
            k = payload.get("key", "")
            if not k.startswith(url + "?"):
                continue
            other = dict(ast.literal_eval(k.split("?", 1)[1]))
        except (ValueError, SyntaxError, OSError):
            continue
        if {a: b for a, b in other.items() if a not in _VARYING} != wanted:
            continue
        value = payload.get("value") or {}
        if value.get("reused_from"):
            continue
        if height is not None and max_dz is not None and (
                value.get("elevation") is None or abs(value["elevation"] - height) > max_dz):
            continue
        d = haversine_km(params["latitude"], params["longitude"],
                         other["latitude"], other["longitude"])
        if d <= max_km and (best is None or (d, -payload.get("stored_at", 0)) < best[0]):
            best = ((d, -payload.get("stored_at", 0)), payload["value"], other)
    if best is None:
        return None
    (_d, _t), value, other = best
    return {**value, "_nearby": {"latitude": other["latitude"], "longitude": other["longitude"],
                                 "distance_km": round(_d, 2)}}


def _reuse(namespace: str, url: str, params: dict, height: float | None,
           fresh_since: str | None = None) -> dict | None:
    """The series of a point within REUSE_KM and REUSE_DZ_M, marked `reused_from`.

    `fresh_since`: a series ending before that day is not reused."""
    if height is None:
        return None
    near = nearby_cached(namespace, url, params, REUSE_KM, height, REUSE_DZ_M)
    if near is None or (fresh_since and _last_day(near) < fresh_since):
        return None
    near["reused_from"] = near.pop("_nearby")
    return near


async def _get_json(url: str, params: dict, namespace: str, height: float | None = None,
                    fresh_since: str | None = None) -> dict:
    key = f"{url}?{sorted(params.items())}"
    hit = cache.get(namespace, key)
    if hit is not None:
        hit["_cached"] = True
        return hit

    reused = _reuse(namespace, url, params, height, fresh_since)
    if reused is not None:
        cache.set(namespace, key, reused)
        reused["_cached"] = True
        reused["_reused"] = True
        return reused

    try:
        data = await _get_with_retry(url, params)
    except (httpx.HTTPError, UpstreamError) as exc:
        if config.OFFLINE_FALLBACK:
            stale = cache.get(namespace, key, allow_stale=True)
            if stale is None:
                stale = nearby_cached(namespace, url, params)
            if stale is not None:
                stale["_cached"] = True
                stale["_stale"] = True
                return stale
        raise UpstreamError(str(exc)) from exc

    if "daily" not in data:
        raise UpstreamError(f"response without a 'daily' block: {str(data)[:200]}")
    cache.set(namespace, key, data)
    data["_cached"] = False
    return data


# Re-requesting 47 years to add a few days is what exhausts the limits; a month less of
# record does not change a 47-year climatology.
RECENT_ENOUGH_DAYS = 30


def archive_end_date_minus(days: int) -> str:
    return (dt.date.fromisoformat(archive_end_date()) - dt.timedelta(days=days)).isoformat()


def _last_day(payload: dict) -> str:
    times = (payload.get("daily") or {}).get("time") or []
    return times[-1] if times else ""


async def fetch_archive(lat: float, lon: float, height: float | None = None) -> dict:
    """ERA5 daily series from ARCHIVE_START until today minus the lag.

    The cache key carries the end date, which changes every day, so the last good
    series of each point is also kept and reused for up to RECENT_ENOUGH_DAYS, and
    served as stale if the API does not respond. `height` (the terrain at the point)
    allows reusing a nearby point's series.
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": config.ARCHIVE_START,
        "end_date": archive_end_date(),
        "daily": ",".join(ARCHIVE_DAILY),
        "timezone": "UTC",
    }
    latest_key = f"{params['latitude']},{params['longitude']}|{','.join(ARCHIVE_DAILY)}"
    latest = cache.get("archive_latest", latest_key, allow_stale=True)
    if latest and _last_day(latest) >= archive_end_date_minus(RECENT_ENOUGH_DAYS):
        latest["_cached"] = True
        return latest
    try:
        data = await _get_json(ARCHIVE_URL, params, "archive", height,
                               fresh_since=archive_end_date_minus(RECENT_ENOUGH_DAYS))
    except UpstreamError:
        stale = cache.get("archive_latest", latest_key, allow_stale=True)
        if stale is None:
            stale = nearby_cached("archive", ARCHIVE_URL, params)
        if stale is None or not config.OFFLINE_FALLBACK:
            raise
        stale["_cached"] = True
        stale["_stale"] = True
        return stale
    if not data.get("_cached") or data.get("_reused"):
        cache.set("archive_latest", latest_key, {k: v for k, v in data.items() if not k.startswith("_")})
    return data


async def fetch_climate(lat: float, lon: float, start: str, end: str,
                        height: float | None = None) -> dict:
    """CMIP6 (HighResMIP) daily series for a future or reference window.

    The HighResMIP future experiments follow an SSP5-8.5-like forcing ("highres-future").
    There is no choice of scenario in this API, and the report says so.
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": start,
        "end_date": end,
        "models": ",".join(config.CLIMATE_MODELS),
        "daily": ",".join(CLIMATE_DAILY),
    }
    return await _get_json(CLIMATE_URL, params, "climate", height)


SNOW_START = "1991-01-01"


async def fetch_snowfall(lat: float, lon: float, height: float | None = None) -> dict:
    """ERA5-Land daily snowfall (cm) since 1991, only for points with avalanche terrain.

    A separate one-variable request, so flat places never pay for it. It ends on the
    last complete year, so its cache key only changes once a year.
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": SNOW_START,
        "end_date": f"{dt.date.today().year - 1}-12-31",
        "daily": "snowfall_sum",
        "timezone": "UTC",
    }
    return await _get_json(ARCHIVE_URL, params, "snow", height)


def summarize_snowfall(payload: dict) -> dict | None:
    """Mean annual snowfall and heavy-snowfall days, over complete years only."""
    daily = payload.get("daily") or {}
    times, values = daily.get("time") or [], daily.get("snowfall_sum") or []
    by_year: dict[int, list[float]] = {}
    for t, v in zip(times, values):
        if v is not None:
            by_year.setdefault(int(t[:4]), []).append(v)
    years = {y: v for y, v in by_year.items() if len(v) >= 360}
    if len(years) < 10:
        return None
    n = len(years)
    heavy = sum(1 for v in years.values() for x in v if x >= 20)
    return {"annual_cm": round(sum(sum(v) for v in years.values()) / n),
            "heavy_days": round(heavy / n, 1),
            "max_day_cm": round(max(max(v) for v in years.values()), 1),
            "period": f"{min(years)}-{max(years)}", "grid_elevation_m": payload.get("elevation")}


def merge_models(payload: dict, variable: str) -> list[float | None]:
    """The Climate API returns one column per model; the multi-model mean is used.

    A single climate model is one realisation, not a forecast.
    """
    daily = payload.get("daily", {})
    columns = [
        values
        for name, values in daily.items()
        if name.startswith(variable) and name != "time"
    ]
    if not columns:
        return []
    n = len(columns[0])
    out: list[float | None] = []
    for i in range(n):
        vals = [c[i] for c in columns if i < len(c) and c[i] is not None]
        out.append(sum(vals) / len(vals) if vals else None)
    return out
