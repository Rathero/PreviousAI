"""Free text -> coordinates, with the real precision of the result.

Three geocoders, each for what it does well:
  - CartoCiudad (IGN): Spanish postal addresses, down to the house number.
  - Nominatim (OpenStreetMap): addresses and places in the rest of the world.
  - Open-Meteo (GeoNames): towns. Fast, but it returns the town's CENTRE.

Every place carries `precision` (address, street, town, place, coordinates) and
`geocoder`: a point card computed on a town centre says nothing about another street.
"""

from __future__ import annotations

import re
import unicodedata

import httpx

from .. import cache, config
from . import cartociudad, nominatim

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
RESOLVE_KEY = "resolve:v4"


class GeocodingError(RuntimeError):
    pass


async def search(query: str, *, count: int = 5, language: str = "en") -> list[dict]:
    params = {"name": query, "count": count, "language": language, "format": "json"}
    key = f"geocode:{query}:{language}:{count}"
    hit = cache.get("geocode", key)
    if hit is not None:
        return hit

    try:
        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT, headers={"User-Agent": config.USER_AGENT}
        ) as client:
            resp = await client.get(GEOCODE_URL, params=params)
        resp.raise_for_status()
        results = resp.json().get("results", []) or []
    except httpx.HTTPError as exc:
        stale = cache.get("geocode", key, allow_stale=True)
        if stale is not None:
            return stale
        raise GeocodingError(f"geocoding unavailable: {exc}") from exc

    places = [
        {
            "name": r.get("name"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "country": r.get("country"),
            "country_code": r.get("country_code"),
            "admin1": r.get("admin1"),
            "admin2": r.get("admin2"),
            "timezone": r.get("timezone"),
            "elevation": r.get("elevation"),
            "population": r.get("population"),
            "label": ", ".join(
                x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x
            ),
            "precision": "town",
            "geocoder": "Open-Meteo (GeoNames)",
        }
        for r in results
    ]
    cache.set("geocode", key, places)
    return places


_COORDS = re.compile(r"^\s*(-?\d{1,2}(?:[.]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.]\d+)?)\s*$")

# The geocoder can return provinces under their Castilian exonym ("Provincia de
# Gerona"), but people type "Girona". Both forms are compared.
_REGION_ALIASES = {
    "girona": "gerona", "lleida": "lerida", "catalunya": "cataluna",
    "ourense": "orense", "a coruna": "coruna", "illes balears": "baleares",
    "comunitat valenciana": "comunidad valenciana", "gipuzkoa": "guipuzcoa",
    "bizkaia": "vizcaya", "araba": "alava", "catalonia": "cataluna",
    "balearic islands": "baleares", "valencian community": "comunidad valenciana",
    "andalusia": "andalucia", "seville": "sevilla",
}

# Street words in the languages most likely to be typed. With one of them, or with a
# number, the query is an address and not a town.
_ADDRESS_WORDS = re.compile(
    r"(^|[\s,])(calle|c/|carrer|avenida|avda\.?|av\.|avinguda|plaza|pla[cç]a|paseo|passeig|"
    r"camino|cam[ií]|ronda|rambla|traves[ií]a|travessera|carretera|ctra\.?|urbanizaci[oó]n|"
    r"street|road|avenue|boulevard|rue|strasse|stra[sß]e|platz|piazza|via|rua)([\s,.]|$)",
    re.IGNORECASE)


def looks_like_address(query: str) -> bool:
    return bool(re.search(r"\d", query or "")) or bool(_ADDRESS_WORDS.search(query or ""))


def parse_coordinates(query: str) -> tuple[float, float] | None:
    """"41.5933, 1.8375" -> (lat, lon). None if they are not valid coordinates."""
    m = _COORDS.match(query or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(c)).lower().strip()


def pick_by_region(places: list[dict], region: str) -> dict | None:
    """First result whose region, province or country contains the given region."""
    wanted = _norm(region)
    forms = {wanted, _REGION_ALIASES.get(wanted, wanted)}
    forms |= {k for k, v in _REGION_ALIASES.items() if v == wanted}
    for place in places:
        haystack = " ".join(_norm(place.get(k) or "") for k in ("admin1", "admin2", "country"))
        if any(f and f in haystack for f in forms):
            return place
    return None


async def _address(query: str) -> dict | None:
    """Postal address: CartoCiudad in Spain and, failing that, Nominatim."""
    try:
        place = await cartociudad.geocode(query)
    except httpx.HTTPError:
        place = None
    if place is None:
        try:
            hit = await nominatim.search(query)
        except httpx.HTTPError:
            hit = None
        place = nominatim.to_place(hit) if hit else None
    return place


async def _town(query: str) -> dict | None:
    place = None
    if "," in query:
        name, region = (part.strip() for part in query.split(",", 1))
        place = pick_by_region(await search(name, count=10), region)
    if place is None:
        places = await search(query, count=1)
        place = places[0] if places else None
    return place


async def resolve(query: str) -> dict:
    """Free text, address, "name, region" or coordinates -> one place.

      - The town index does not understand "name, region": the name is searched and
        the result in that region is chosen.
      - Natural sites are not towns: coordinates are accepted for them.
      - Addresses go to CartoCiudad and Nominatim, which know streets and numbers.
    """
    coords = parse_coordinates(query)
    if coords:
        lat, lon = coords
        return {"name": f"{lat:.4f}, {lon:.4f}", "label": f"{lat:.4f}, {lon:.4f}",
                "latitude": lat, "longitude": lon, "country": None, "country_code": None,
                "admin1": None, "admin2": None, "timezone": None, "elevation": None,
                "from_coordinates": True, "precision": "coordinates", "geocoder": None}

    key = f"{RESOLVE_KEY}:{query}"
    hit = cache.get("geocode", key)
    if hit is not None:
        return hit

    place = None
    if looks_like_address(query):
        place = await _address(query)
        if place is None and "," in query:
            # The address is not found: fall back to the town centre, and say so.
            town = await _town(query.rsplit(",", 1)[1].strip())
            if town:
                place = {**town, "address_not_found": query}
    if place is None:
        place = await _town(query)
    if place is None:
        try:
            hit = await nominatim.search(query)
        except httpx.HTTPError:
            hit = None
        place = nominatim.to_place(hit) if hit else None
    if place is None:
        raise GeocodingError(
            f"We could not find \"{query}\". Try \"street and number, town\", or the town "
            f"and its province."
        )
    cache.set("geocode", key, place)
    return place


async def suggest(query: str, limit: int = 6) -> list[dict]:
    """Address suggestions while typing: Spanish addresses (CartoCiudad).

    Nominatim's usage policy forbids autocomplete, so outside Spain the address is
    geocoded only when it is submitted.
    """
    query = " ".join((query or "").split())
    if len(query) < 3:
        return []
    try:
        return await cartociudad.candidates(query, limit=limit)
    except httpx.HTTPError:
        return []
