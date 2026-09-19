"""Official Catalan wildfire danger · Government of Catalonia. Catalonia only, no key.

Two official answers to two different questions:

  - INFOCAT municipal class (Directorate-General for Civil Protection, open data): how
    prone the municipality is to wildfire compared with the Catalan average (static
    danger, from terrain, fuel and fire history) and how vulnerable it is (homes,
    urbanisations and infrastructure next to forest). It is long-term but municipal: an
    official contrast on the wildfire card that does not score.
  - Pla Alfa (Agents Rurals): today's operational fire danger level, 0 (low) to 4
    (extreme), per municipality, updated at 00:00 and 09:30. It is about today, so it
    never scores.

The sources speak Catalan; everything is translated here, at the edge.

Pla Alfa layer: the official viewer reads `Pla_Alfa_Municipal_Avui_FL_alternatiu_VW`. A
similarly named layer (`..._2_view`) answers too but is not kept up to date, and the
"tomorrow" municipal layer publishes no values, so tomorrow is not offered.
"""

from __future__ import annotations

import datetime as dt

import httpx

from .. import cache, config

INFOCAT_URL = "https://analisi.transparenciacatalunya.cat/resource/eqag-gzjs.json"
INFOCAT_VIEW = "https://analisi.transparenciacatalunya.cat/api/views/eqag-gzjs.json"
INFOCAT_PAGE = ("https://analisi.transparenciacatalunya.cat/Seguretat/Obligacions-i-vig-ncies-dels-"
                "plans-de-protecci-civil-m/eqag-gzjs")
INFOCAT_TTL_S = 30 * 24 * 3600

_ARCGIS = "https://services7.arcgis.com/ZCqVt1fRXwwK6GF4/arcgis/rest/services"
PLA_ALFA_URL = f"{_ARCGIS}/Pla_Alfa_Municipal_Avui_FL_alternatiu_VW/FeatureServer/0/query"
# The regional layer carries the date and time of the issue in force.
PLA_ALFA_ISSUE_URL = f"{_ARCGIS}/Pla_Alfa_Comarcal_Avui_FL_VW/FeatureServer/1/query"
PLA_ALFA_PAGE = "https://interior.gencat.cat/ca/arees_dactuacio/agents-rurals/pla-alfa/"
PLA_ALFA_TTL_S = 30 * 60

# Order matters: the longest label first, so "Molt superior" is not read as "Superior".
DANGER_EN = [
    ("molt inferior a la mitjana", "well below the Catalan average", 1),
    ("inferior a la mitjana", "below the Catalan average", 2),
    ("centrat a la mitjana", "around the Catalan average", 3),
    ("molt superior a la mitjana", "well above the Catalan average", 5),
    ("superior a la mitjana", "above the Catalan average", 4),
]
VULNERABILITY_EN = [
    ("molt baixa", "very low", 1), ("baixa", "low", 2), ("mitjana", "medium", 3),
    ("mitja", "medium", 3), ("molt alta", "very high", 5), ("alta", "high", 4),
]
OBLIGATION_EN = {
    "obligat": "required",
    "recomanat": "recommended",
    "no obligat ni recomanat": "neither required nor recommended",
}
PLAN_STATUS_EN = {
    "homologat": "approved",
    "pendent de revisió": "pending review",
    "pendent d'homologació": "pending approval",
    "no elaborat": "not drawn up",
}


def _match(text: str, table: list[tuple[str, str, int]]) -> tuple[str, int] | None:
    t = text.strip().lower()
    for ca, en, rank in table:
        if t.startswith(ca):
            return en, rank
    return None


def parse_criteria(criteria: str | None) -> dict:
    """"Vulnerabilitat: Molt alta; Perill: Inferior a la mitjana" -> classes in English."""
    out: dict = {}
    for part in (criteria or "").split(";"):
        if ":" not in part:
            continue
        name, value = (s.strip() for s in part.split(":", 1))
        name = name.lower()
        if name.startswith("perill"):
            hit = _match(value, DANGER_EN)
            if hit:
                out["danger"], out["danger_rank"] = hit
            out["danger_ca"] = value
        elif name.startswith("vulnerabilitat"):
            hit = _match(value, VULNERABILITY_EN)
            if hit:
                out["vulnerability"], out["vulnerability_rank"] = hit
            out["vulnerability_ca"] = value
    return out


def parse_infocat_row(row: dict) -> dict:
    obligation = (row.get("obligaci") or "").strip()
    status = (row.get("vig_ncia_pla") or "").strip()
    return {
        "municipality": row.get("municipi"),
        "ine5": row.get("ine5"),
        **parse_criteria(row.get("criteris_afectaci")),
        "plan": OBLIGATION_EN.get(obligation.lower(), obligation.lower() or None),
        "plan_ca": obligation or None,
        "plan_status": PLAN_STATUS_EN.get(status.lower(), status.lower() or None),
        "plan_approved": (row.get("data_d_homologaci_del_pla") or "")[:10] or None,
    }


async def _infocat_table() -> dict:
    """All municipalities' INFOCAT rows (one request, ~950 rows), keyed by INE code."""
    key = "infocat:v1"
    table = cache.get("gencat_fire", key, ttl=INFOCAT_TTL_S)
    if table is not None:
        return table
    try:
        async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                     headers={"User-Agent": config.USER_AGENT}) as client:
            resp = await client.get(INFOCAT_URL, params={
                "$where": "pla_generalitat='INFOCAT'", "$limit": 5000})
            resp.raise_for_status()
            rows = resp.json()
            updated = None
            try:
                meta = (await client.get(INFOCAT_VIEW)).json()
                stamp = meta.get("rowsUpdatedAt")
                if stamp:
                    updated = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat()
            except (httpx.HTTPError, ValueError):
                pass
    except (httpx.HTTPError, ValueError):
        table = cache.get("gencat_fire", key, allow_stale=True)
        if table is None:
            raise
        return table
    table = {"updated": updated, "rows": {r["ine5"]: r for r in rows if r.get("ine5")}}
    cache.set("gencat_fire", key, table)
    return table


async def infocat(municipality_code: str) -> dict | None:
    """The municipality's INFOCAT classes. `municipality_code` is the 6-digit Catalan code
    (INE + check digit); the table uses the 5-digit INE code."""
    table = await _infocat_table()
    row = table["rows"].get(str(municipality_code)[:5])
    if not row:
        return None
    return {**parse_infocat_row(row), "updated": table.get("updated"),
            "source": "Civil Protection · Government of Catalonia", "url": INFOCAT_PAGE}


PLA_ALFA_LEVELS = {0: "low", 1: "moderate", 2: "high", 3: "very high", 4: "extreme"}
# What each level implies, summarised from the official page.
PLA_ALFA_WHAT = {
    0: "activities with fire risk need the usual authorisation or notice",
    1: "activities with fire risk need the usual authorisation or notice",
    2: "activities with fire risk need the usual authorisation or notice",
    3: "no fires in the open, including picnic and camping areas; authorised burns and "
       "machinery that can spark within 500 m of forest are suspended",
    4: "extraordinary measures: access to protected natural areas and busy forests may be "
       "restricted, except for residents and essential services",
}


def parse_pla_alfa(features: list[dict], issue: list[dict] | None = None) -> dict | None:
    if not features:
        return None
    a = features[0].get("attributes", {})
    level = a.get("PERIL_M")
    if level not in PLA_ALFA_LEVELS:
        return None  # 5 = no value published
    issued = None
    if issue:
        b = issue[0].get("attributes", {})
        if b.get("DATA"):
            day = dt.datetime.fromtimestamp(b["DATA"] / 1000, dt.timezone.utc).date().isoformat()
            issued = f"{day} {b.get('HORA') or ''}".strip()
    return {"level": level, "label": PLA_ALFA_LEVELS[level], "means": PLA_ALFA_WHAT[level],
            "municipality": a.get("NOMMUNI"), "code": a.get("CODIMUNI"), "issued": issued,
            "source": "Pla Alfa · Agents Rurals, Government of Catalonia", "url": PLA_ALFA_PAGE}


async def pla_alfa(lat: float, lon: float) -> dict | None:
    key = f"pla_alfa:{lat:.4f},{lon:.4f}"
    hit = cache.get("gencat_fire", key, ttl=PLA_ALFA_TTL_S)
    if hit is not None:
        return hit
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "NOMMUNI,CODIMUNI,PERIL_M",
              "returnGeometry": "false", "f": "json"}
    try:
        async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                     headers={"User-Agent": config.USER_AGENT}) as client:
            resp = await client.get(PLA_ALFA_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise ValueError(body["error"])
            issue = []
            try:
                meta = (await client.get(PLA_ALFA_ISSUE_URL, params={
                    "where": "1=1", "outFields": "DATA,HORA", "returnGeometry": "false",
                    "resultRecordCount": 1, "f": "json"})).json()
                issue = meta.get("features", [])
            except (httpx.HTTPError, ValueError):
                pass
    except (httpx.HTTPError, ValueError):
        # An old level is still dated (`issued`), so its age can be shown.
        stale = cache.get("gencat_fire", key, allow_stale=True)
        if stale is None:
            raise
        return {**stale, "stale": True}
    result = parse_pla_alfa(body.get("features", []), issue)
    cache.set("gencat_fire", key, result)
    return result
