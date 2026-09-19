"""15-day ensemble forecast. It is NOT risk: it is what is coming.

The report measures long-term hazard (decades of ERA5, projections to 2050). This answers
another question: is anything out of the ordinary coming in the next two weeks? It never
counts towards the score and is always shown next to what is usual for those dates.

Swappable source (`FORECAST_PROVIDER`):
  - `ecmwf-aifs` (default): AIFS ENS, ECMWF's AI model, 51 ensemble members at 0.25°,
    via the Open-Meteo Ensemble API. No key.
  - `ecmwf-ifs`: ECMWF's physics model (51 members). Its last day can come back empty.

Every adapter returns the same thing: per variable and day, the value of each member.
"""

from __future__ import annotations

import httpx

from .. import cache, config

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
VARIABLES = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"]
TTL_S = 3 * 3600  # ECMWF publishes every 6-12 hours

PROVIDERS = {
    "ecmwf-aifs": {
        "model": "ecmwf_aifs025_ensemble",
        "provenance": dict(
            source="ECMWF AIFS ENS · the European Centre's AI forecast model, via the "
                   "Open-Meteo Ensemble API",
            dataset="ecmwf-aifs025-ensemble",
            resolution="0.25 degrees (~28 km)",
            url="https://open-meteo.com/en/docs/ensemble-api",
            scale="~28 km grid", scale_kind="grid",
        ),
        "licence": "ECMWF open data (CC BY 4.0)",
    },
    "ecmwf-ifs": {
        "model": "ecmwf_ifs025",
        "provenance": dict(
            source="ECMWF IFS ENS · the European Centre's physics model, via the Open-Meteo Ensemble API",
            dataset="ecmwf-ifs025-ensemble",
            resolution="0.25 degrees (~28 km)",
            url="https://open-meteo.com/en/docs/ensemble-api",
            scale="~28 km grid", scale_kind="grid",
        ),
        "licence": "ECMWF open data (CC BY 4.0)",
    },
}


class ForecastUnavailable(RuntimeError):
    pass


def provider_name() -> str:
    return config.FORECAST_PROVIDER or "ecmwf-aifs"


def members_by_variable(daily: dict) -> dict[str, list[list[float | None]]]:
    """Columns "var", "var_member01", … -> {var: [[members for day 0], …]}.

    The column without a suffix is the control member: it counts as one more.
    """
    days = len(daily.get("time", []))
    out = {}
    for var in VARIABLES:
        cols = [v for k, v in daily.items() if k == var or k.startswith(var + "_member")]
        out[var] = [[col[i] for col in cols if i < len(col)] for i in range(days)]
    return out


async def _open_meteo(lat: float, lon: float, spec: dict) -> dict:
    params = {"latitude": round(lat, 2), "longitude": round(lon, 2), "daily": ",".join(VARIABLES),
              "models": spec["model"], "forecast_days": 15, "timezone": "auto"}
    key = f"{ENSEMBLE_URL}?{sorted(params.items())}"
    hit = cache.get("forecast", key, ttl=TTL_S)
    if hit is None:
        try:
            async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                         headers={"User-Agent": config.USER_AGENT}) as client:
                resp = await client.get(ENSEMBLE_URL, params=params)
            data = resp.json()
            if resp.status_code >= 400 or data.get("error"):
                raise ForecastUnavailable(f"Open-Meteo Ensemble: {data.get('reason') or resp.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            raise ForecastUnavailable(f"Open-Meteo Ensemble is not responding: {exc}") from exc
        hit = {"dates": data["daily"]["time"], "members": members_by_variable(data["daily"]),
               "grid": [data.get("latitude"), data.get("longitude")],
               "timezone": data.get("timezone")}
        cache.set("forecast", key, hit)
    return hit


async def ensemble(lat: float, lon: float) -> dict:
    name = provider_name()
    spec = PROVIDERS.get(name)
    if spec is None:
        raise ForecastUnavailable(f"unknown forecast provider: {name!r}")
    data = await _open_meteo(lat, lon, spec)
    return {**data, "provider": name, "provenance": spec["provenance"], "licence": spec["licence"]}
