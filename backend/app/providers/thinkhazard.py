"""Hazard level by region from ThinkHazard! (GFDRR, World Bank). Worldwide.

Used for flooding where there is no official street-scale map, and as a regional second
opinion on heat and wildfire. It is REGIONAL coverage (province or district) and every
card that uses it says so.

From coordinates to a region, because the API does not do it:
  1. Reverse geocoding with Nominatim (OpenStreetMap), in English.
  2. ThinkHazard's own search (`/en/administrativedivision?q=`).
  3. Matching by country and name, tolerant of the usual differences ("Maricopa
     County" vs "Maricopa", "United States" vs "United States of America", bilingual
     names like "Valencia/València").
"""

from __future__ import annotations

import re
import unicodedata

import httpx

from .. import cache, config
from . import nominatim

SEARCH_URL = "https://thinkhazard.org/en/administrativedivision"
REPORT_URL = "https://thinkhazard.org/en/report/{code}.json"

HAZARD_EN = {
    "FL": "River flood", "UF": "Urban flood", "CF": "Coastal flood",
    "EQ": "Earthquake", "LS": "Landslide", "TS": "Tsunami", "VA": "Volcano",
    "CY": "Cyclone", "DG": "Water scarcity", "EH": "Extreme heat", "WF": "Wildfire",
}
LEVEL_EN = {"HIG": "high", "MED": "medium", "LOW": "low", "VLO": "very low", "no-data": "no data"}
LEVEL_ORDER = {"no-data": -1, "VLO": 0, "LOW": 1, "MED": 2, "HIG": 3}

_SUFFIXES = re.compile(r"\s+(county|province|regency|district|department|prefecture|municipality)$")


def norm(text: str | None) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", text or "")
                if not unicodedata.combining(c)).lower().strip()
    t = re.sub(r"^(provincia de|province of|comarca de|county of)\s+", "", t)
    return _SUFFIXES.sub("", t).strip()


def country_matches(a: str | None, b: str | None) -> bool:
    na, nb = norm(a), norm(b)
    return bool(na and nb) and (na == nb or na.startswith(nb) or nb.startswith(na))


def pick_division(candidates: list[dict], name: str, country: str) -> dict | None:
    """The candidate in the right country whose admin2 (or admin1) matches the name."""
    wanted = norm(name)
    same_country = [c for c in candidates if country_matches(c.get("admin0"), country)]
    for c in same_country:
        if c.get("admin2") and wanted in [norm(p) for p in c["admin2"].split("/")]:
            return c
    for c in same_country:
        admin1 = [norm(p) for p in (c.get("admin1") or "").split("/")]
        if not c.get("admin2") and wanted in admin1:
            return c
    return None


def admin_names(address: dict) -> list[str]:
    """Names to try, from the most specific to the most general."""
    out = []
    for key in ("state_district", "county", "province", "state", "city"):
        value = address.get(key)
        if value and value not in out:
            out.append(value)
    return out


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None, ns: str, key: str):
    hit = cache.get(ns, key)
    if hit is not None:
        return hit
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    cache.set(ns, key, data)
    return data


async def regional_levels(lat: float, lon: float, hint: dict | None = None) -> dict:
    """ThinkHazard levels for the point's region.

    `hint` skips Nominatim when the province is already known:
    {"names": [...], "country": "Spain"}.
    """
    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        if hint:
            names, country = hint["names"], hint["country"]
        else:
            address = await nominatim.reverse(lat, lon)
            names, country = admin_names(address), address.get("country")
        if not country:
            return {"division": None, "levels": {}, "reason": "no country for the point"}

        division = None
        for name in names:
            found = await _get_json(client, SEARCH_URL, {"q": name}, "thinkhazard",
                                    f"search:{name}")
            division = pick_division(found.get("data", []), name, country)
            if division:
                break
        if division is None:  # last resort: the whole country
            found = await _get_json(client, SEARCH_URL, {"q": country}, "thinkhazard",
                                    f"search:{country}")
            division = next((c for c in found.get("data", [])
                             if country_matches(c.get("admin0"), country)
                             and not c.get("admin1")), None)
        if division is None:
            return {"division": None, "levels": {}, "reason": f"no ThinkHazard region for {names}"}

        report = await _get_json(client, REPORT_URL.format(code=division["code"]), None,
                                 "thinkhazard", f"report:{division['code']}")

    levels = {item["hazardtype"]["mnemonic"]: item["hazardlevel"]["mnemonic"] for item in report}
    scope = "admin2" if division.get("admin2") else "admin1" if division.get("admin1") else "country"
    label = " · ".join(x for x in (division.get("admin2"), division.get("admin1"),
                                   division.get("admin0")) if x)
    return {"division": {**division, "scope": scope, "label": label},
            "levels": levels, "source": "https://thinkhazard.org/"}
