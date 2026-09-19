"""Spanish postal addresses · CartoCiudad (IGN and Cadastre). No key.

It gives house-number precision: "Carrer de la Força 5, Girona" returns the exact
building entrance and its cadastral reference.

Behaviours of the service this module handles:
  - `find` returns the best candidate; if it is a PORTAL (house number) it carries
    coordinates.
  - If it is a STREET without a number, the coordinates come back as 0 and its geometry
    has to be requested (`find` with `type` and `id`): the middle vertex is used.
  - It can return another municipality without warning, so the municipality is
    required to appear in what was typed.
"""

from __future__ import annotations

import re
import unicodedata

import httpx

from .. import cache, config

FIND_URL = "https://www.cartociudad.es/geocoder/api/geocoder/find"
CANDIDATES_URL = "https://www.cartociudad.es/geocoder/api/geocoder/candidates"
SUGGEST_TTL_S = 7 * 24 * 3600

_SMALL_WORDS = {"de", "del", "dels", "la", "les", "el", "els", "i", "y", "d", "l"}


def norm(text: str | None) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", text or "")
                if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def tidy(text: str | None) -> str:
    """"CALLE MALLORCA" -> "Calle Mallorca"; "CARRER DE LA FORÇA" -> "Carrer de la Força"."""
    if not text:
        return ""
    words = []
    for i, word in enumerate(text.strip().lower().split()):
        parts = re.split(r"(['’])", word)
        out = []
        for part in parts:
            if part in ("'", "’") or not part:
                out.append(part)
            elif i > 0 and part in _SMALL_WORDS:
                out.append(part)
            else:
                out.append(part[:1].upper() + part[1:])
        words.append("".join(out))
    return " ".join(words)


def municipality_matches(hit: dict, query: str) -> bool:
    q = f" {norm(query)} "
    names = {norm(hit.get(k)) for k in ("muni", "poblacion") if hit.get(k)}
    # Also the form without the article ("L'Hospitalet" -> "hospitalet").
    names |= {re.sub(r"^(l|la|el|les|els|los|las) ", "", n) for n in names}
    return any(n and f" {n} " in q for n in names)


def midpoint_of_wkt(wkt: str | None) -> tuple[float, float] | None:
    """Middle vertex of a POINT/LINESTRING/MULTILINESTRING in WKT (lon lat)."""
    pairs = re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", wkt or "")
    if not pairs:
        return None
    lon, lat = pairs[len(pairs) // 2]
    return float(lat), float(lon)


def to_place(hit: dict, lat: float, lon: float, precision: str) -> dict:
    via = (hit.get("tip_via") or "").title()
    street = " ".join(x for x in (via, (hit.get("address") or "").title(),
                                  str(hit["portalNumber"]) if hit.get("portalNumber") else "") if x)
    town = hit.get("poblacion") or hit.get("muni")
    return {
        "name": street or town,
        "label": ", ".join(x for x in (street, town) if x),
        "latitude": lat, "longitude": lon,
        "country": "Spain", "country_code": "ES",
        "admin1": hit.get("comunidadAutonoma"), "admin2": hit.get("province"),
        "town": town,
        "timezone": "Europe/Madrid", "elevation": None,
        "precision": precision, "geocoder": "CartoCiudad (IGN)",
        "ref_catastral": hit.get("refCatastral"), "postal_code": hit.get("postalCode"),
    }


async def _find(client: httpx.AsyncClient, params: dict) -> dict | None:
    key = f"find:{sorted(params.items())}"
    hit = cache.get("cartociudad", key)
    if hit is not None:
        return hit or None
    resp = await client.get(FIND_URL, params=params)
    resp.raise_for_status()
    data = resp.json() if resp.text.strip() else {}
    cache.set("cartociudad", key, data or {})
    return data or None


async def geocode(query: str) -> dict | None:
    """Spanish address -> place with house-number or street precision, or None."""
    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        hit = await _find(client, {"q": query})
        if not hit or not municipality_matches(hit, query):
            return None
        kind = hit.get("type")
        if kind == "portal" and hit.get("lat"):
            return to_place(hit, float(hit["lat"]), float(hit["lng"]), "address")
        if kind == "callejero":
            full = await _find(client, {"q": query, "type": kind, "id": hit.get("id")})
            point = midpoint_of_wkt((full or {}).get("geom"))
            if point:
                return to_place(full, *point, "street")
    return None


def _suggestion(c: dict) -> dict | None:
    """A candidate as the address box shows it, and the text that geocodes back to it."""
    raw = (c.get("address") or "").strip()
    if not raw:
        return None
    street = raw.split(",")[0].strip()
    town = c.get("poblacion") or c.get("muni") or ""
    kind = c.get("type")
    if kind == "portal":
        precision = "address"
    elif kind == "callejero":
        precision = "street"
    elif kind in ("Municipio", "poblacion", "municipio"):
        precision = "town"
    else:
        precision = "place"
    line1 = tidy(street) if street else tidy(town)
    line2 = ", ".join(x for x in (c.get("postalCode"), town if street else None, c.get("province"))
                      if x and x != line1)
    text = f"{line1}, {town}" if street and town else line1
    return {"text": text, "line1": line1, "line2": line2, "precision": precision}


async def candidates(query: str, limit: int = 6) -> list[dict]:
    """Address suggestions for the address box (Spain)."""
    key = f"candidates:{norm(query)}:{limit}"
    hit = cache.get("cartociudad", key, ttl=SUGGEST_TTL_S)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": config.USER_AGENT}) as client:
        resp = await client.get(CANDIDATES_URL, params={"q": query, "limit": limit})
        resp.raise_for_status()
        data = resp.json() if resp.text.strip() else []
    out, seen = [], set()
    for c in data if isinstance(data, list) else []:
        s = _suggestion(c)
        if s and s["text"].lower() not in seen:
            seen.add(s["text"].lower())
            out.append(s)
    cache.set("cartociudad", key, out)
    return out[:limit]
