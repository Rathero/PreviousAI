"""Builds the national analysis: every municipality ranked, then its buildings.

The report asks one address what threatens it. This asks the country which homes are
threatened, and it is built in batch because a ranking that recomputed itself would be
a different ranking every time somebody opened it.

    python backend/scripts/analysis_build.py --only universe      # who exists
    python backend/scripts/analysis_build.py --only climate       # the fire-danger grid
    python backend/scripts/analysis_build.py --only catalonia     # the Catalan layers
    python backend/scripts/analysis_build.py --only exposure --municipality 46188
    python backend/scripts/analysis_build.py --only exposure --province 46 --top 10
    python backend/scripts/analysis_build.py --only screen        # all of Spain, cheap
    python backend/scripts/analysis_build.py --only exposure --per-province 10
    python backend/scripts/analysis_build.py --only assets        # TALAIA, needs a key
    python backend/scripts/analysis_build.py --only heat --top 25 # ERA5, quota allowing
    python backend/scripts/analysis_build.py --only ranking       # assemble
    python backend/scripts/analysis_build.py                      # all of the above

Each block writes its own file and can be re-run on its own; `--only ranking` is cheap
and only reassembles what the others left on disk.

The blocks, and why each one is shaped the way it is:

  universe   The list of municipalities comes from the cadastre's own ATOM feeds,
             because they are the index of the building downloads used later, and each
             entry already carries the town's bounding box. It is the register of
             common regime: the Basque provinces and Navarre keep their own cadastre
             and are not in it, and the build says so rather than quietly missing 400
             towns.
  climate    Offline. The EURO-CORDEX fire-danger grid was already downloaded for the
             reports (data/cds), and it is the only climate layer that covers all of
             Spain without asking anything of anyone.
  screen     Cheap and national. `resultType=hits` asks the flood WFS for a COUNT and
             no geometry - 510 bytes, a tenth of a second - so every town in Spain can
             be asked whether any official zone reaches it at all: 66 minutes for the
             7,597, and a third of them answer no. That answer is worth having on its
             own, and it is what aims the expensive step below.
  exposure   The expensive one, and the only one that is per building. It downloads a
             municipality's cadastral footprints (about 1.5 MB) and the official flood
             polygons over its bounding box, then crosses them. This is the same
             question providers/miteco.py asks for one point, asked once per building.
  assets     TALAIA: who and what stands in the flood zone the exposure found - the
             schools, care homes, farms and hazardous sites, with their capacity and a
             replacement valuation, and the census population of the ground. The
             cadastre cannot say any of it. Needs TALAIA_API_KEY; without it the step
             says so and changes nothing.
  heat       ERA5 through Open-Meteo, whose free tier is capped per day. It is asked
             only for the municipalities named, it stops at the first quota error and
             what it did not reach stays null instead of being guessed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import httpx  # noqa: E402

from app import analysis, config, geo, scoring, spatial  # noqa: E402
from app.providers import cds_layers  # noqa: E402

OUT = config.ANALYSIS_DIR
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
(OUT / "exposure").mkdir(parents=True, exist_ok=True)

CATASTRO = "https://www.catastro.hacienda.gob.es/INSPIRE"
MITECO_WFS = "https://gis.miteco.gob.es/geoserver/agua/ows"

# Provinces of the cadastre of common regime. 01/20/48 (Basque Country) and 31
# (Navarre) keep their own cadastre and publish no INSPIRE feed here.
FORAL = {"01", "20", "31", "48"}
PROVINCES = [f"{i:02d}" for i in range(1, 53) if f"{i:02d}" not in FORAL]

# A public government server. One request at a time, with a pause between them. The
# screen's pause is shorter because its request is: `resultType=hits` returns 510 bytes
# and no geometry, against the megabytes a real query pulls.
PAUSE = 0.7
SCREEN_PAUSE = 0.15
TIMEOUT = 180.0

HEADERS = {"User-Agent": config.USER_AGENT}


def log(*parts) -> None:
    print(*parts, flush=True)


def fold(text: str) -> str:
    stripped = unicodedata.normalize("NFD", str(text))
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").lower()


XML_ENCODING_RE = re.compile(rb'<\?xml[^>]*?encoding="([^"]+)"', re.I)


def decode(raw: bytes) -> str:
    """Text, in the encoding the document itself declares.

    The cadastre's ATOM feeds are ISO-8859-1 and say so in their XML declaration.
    Reading them as UTF-8 turns "Almería" into "Almer?a" and "Llançà" into "Llan?à",
    which then breaks every match made on a name.
    """
    m = XML_ENCODING_RE.match(raw[:200])
    encoding = m.group(1).decode("ascii", "replace") if m else "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch(client: httpx.Client, url: str, *, params=None, cache: Path | None = None,
          binary: bool = False, pause: float | None = None):
    """One request, cached on disk. Raw downloads are kept so a re-run is free."""
    if cache and cache.exists():
        raw = cache.read_bytes()
        return raw if binary else decode(raw)
    resp = client.get(url, params=params)
    resp.raise_for_status()
    time.sleep(PAUSE if pause is None else pause)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(resp.content)
    return resp.content if binary else decode(resp.content)


# --------------------------------------------------------------------------- #
# universe: which municipalities exist, where they are
# --------------------------------------------------------------------------- #

ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.S)
TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.S)
HREF_RE = re.compile(r'href="([^"]+)"')
POLY_RE = re.compile(r"<georss:polygon>(.*?)</georss:polygon>", re.S)
CODE_RE = re.compile(r"^(\d{5})-(.+?)\s+(?:Cadastral Parcels|buildings)$", re.I)


def parse_feed(xml: str) -> list[dict]:
    """The municipalities of one province feed: code, name, bounding box."""
    out = []
    for block in ENTRY_RE.findall(xml):
        title = TITLE_RE.search(block)
        href = HREF_RE.search(block)
        if not title or not href:
            continue
        m = CODE_RE.match(title.group(1).strip())
        if not m:
            continue
        code, name = m.group(1), m.group(2).strip()
        entry = {"code": code, "name": name, "url": href.group(1)}
        poly = POLY_RE.search(block)
        if poly:
            nums = [float(v) for v in poly.group(1).split()]
            lats, lons = nums[0::2], nums[1::2]
            entry["bbox"] = [min(lons), min(lats), max(lons), max(lats)]  # w,s,e,n
            entry["centroid"] = [round(sum(lats) / len(lats), 5),
                                 round(sum(lons) / len(lons), 5)]
        out.append(entry)
    return out


def province_names(client: httpx.Client) -> dict[str, str]:
    xml = fetch(client, f"{CATASTRO}/buildings/ES.SDGC.BU.atom.xml",
                cache=RAW / "bu_index.xml")
    names = {}
    for block in ENTRY_RE.findall(xml):
        title = TITLE_RE.search(block)
        if not title:
            continue
        m = re.match(r"Territorial office (\d{2})\s+(.+)$", title.group(1).strip())
        if m:
            names[m.group(1)] = m.group(2).strip()
    return names


def build_universe(client: httpx.Client) -> dict:
    log("universe: reading the cadastre's province feeds")
    names = province_names(client)
    municipalities, missing = [], []
    for pp in PROVINCES:
        try:
            cp = fetch(client, f"{CATASTRO}/CadastralParcels/{pp}/ES.SDGC.CP.atom_{pp}.xml",
                       cache=RAW / f"cp_{pp}.xml")
            bu = fetch(client, f"{CATASTRO}/buildings/{pp}/ES.SDGC.bu.atom_{pp}.xml",
                       cache=RAW / f"bu_{pp}.xml")
        except httpx.HTTPError as exc:
            missing.append(f"{pp}: {type(exc).__name__}")
            log(f"  {pp} unavailable ({type(exc).__name__})")
            continue
        boxes = {m["code"]: m for m in parse_feed(cp)}
        builds = {m["code"]: m["url"] for m in parse_feed(bu)}
        for code, entry in boxes.items():
            municipalities.append({
                "code": code,
                "name": entry["name"].title(),
                "province_code": pp,
                "province": names.get(pp, pp),
                "bbox": entry.get("bbox"),
                "centroid": entry.get("centroid"),
                "buildings_url": builds.get(code),
            })
        log(f"  {pp} {names.get(pp, ''):<22} {len(boxes):>4} municipalities")

    payload = {
        "version": analysis.VERSION,
        "built": dt.date.today().isoformat(),
        "municipalities": sorted(municipalities, key=lambda m: m["code"]),
        "provinces": sorted({(m["province_code"], m["province"]) for m in municipalities}),
        "not_covered": {
            "provinces": sorted(FORAL),
            "reason": "the Basque provinces and Navarre keep their own cadastre and "
                      "publish no INSPIRE feed in this service",
        },
        "errors": missing,
    }
    payload["provinces"] = [{"code": c, "name": n} for c, n in payload["provinces"]]
    analysis.write(analysis.MUNICIPALITIES, payload)
    log(f"universe: {len(municipalities)} municipalities -> {analysis.MUNICIPALITIES.name}")
    return payload


def load_universe() -> dict:
    data = analysis.read(analysis.MUNICIPALITIES)
    if not data:
        raise SystemExit("universe is missing: run --only universe first")
    return data


# --------------------------------------------------------------------------- #
# climate: the fire-danger grid, offline
# --------------------------------------------------------------------------- #

def build_climate() -> None:
    data = load_universe()
    grid = cds_layers.fire_data()
    if not grid:
        log("climate: data/cds/fire_danger_projections.json.gz is missing, skipped")
        return
    hit = 0
    for m in data["municipalities"]:
        if not m.get("centroid"):
            continue
        lat, lon = m["centroid"]
        proj = cds_layers.fire_projection(lat, lon, grid)
        if not proj:
            continue
        base = (proj.get("historical_1981_2005") or {}).get("high")
        fut = (proj.get("rcp8_5_2041_2060") or {}).get("high")
        if base is None:
            continue
        m["fire_weather_days"] = round(base, 1)
        m["fire_weather_2050"] = round(fut, 1) if fut is not None else None
        if fut is not None:
            m["fire_weather_context"] = (
                f"{fut - base:+.0f} days a year by 2041-2060 under RCP8.5")
        hit += 1
    analysis.write(analysis.MUNICIPALITIES, data)
    log(f"climate: {hit} of {len(data['municipalities'])} municipalities have a cell "
        f"within 25 km")


# --------------------------------------------------------------------------- #
# catalonia: the layers already on disk for the reports
# --------------------------------------------------------------------------- #

def _box_iou(a, b) -> float:
    """Intersection over union of two boxes, both in the same projected CRS."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    union = ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def _read_gz(path: Path):
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def build_catalonia() -> None:
    """AGORA episodes, Catalan fire statistics and ICGC avalanche zones, per town.

    The two registers do not share a key. Catalan codes carry the INE control digit
    ('080193' -> INE 08019), and the cadastre uses its own: it agrees with INE for most
    towns but gives the provincial capitals a 900 ('08900' IS Barcelona), so matching on
    the code alone silently loses 120 municipalities, the four capitals among them.
    Names do not travel either ('Lleida' against 'Lérida').

    So they are matched on the ground: the cadastre's municipality sits where its
    centre falls inside the Catalan polygon. The code each register uses is kept, so a
    row can be joined back to either.
    """
    data = load_universe()
    muni = _read_gz(config.CATALONIA_DIR / "municipalities.json.gz")
    agora = _read_gz(config.CATALONIA_DIR / "agora_episodes.json.gz")
    fires = _read_gz(config.CATALONIA_DIR / "fire_stats.json.gz")
    aval = _read_gz(config.CATALONIA_DIR / "avalanches.json.gz")
    if not muni:
        log("catalonia: data/catalonia is missing, skipped")
        return

    episodes = {k: len(v) for k, v in ((agora or {}).get("by_municipality") or {}).items()}
    fire_rows = {
        code: {"fires_count": len(rows),
               "burnt_ha": round(sum(float(r.get("haforestal") or 0) for r in rows), 1)}
        for code, rows in (fires or {}).items()
    }

    # Avalanche zones whose centre falls inside the municipality (UTM 31, as stored).
    zones_by_muni: dict[str, int] = {}
    for zone in (aval or {}).get("zones", []):
        bb = zone.get("bbox")
        if not bb:
            continue
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        for cat in muni:
            mb = cat.get("bbox")
            if not mb or not (mb[0] <= cx <= mb[2] and mb[1] <= cy <= mb[3]):
                continue
            if geo.point_in_multipolygon(cx, cy, cat["polygons"]):
                zones_by_muni[cat["code"]] = zones_by_muni.get(cat["code"], 0) + 1
                break

    catalan_provinces = {"08", "17", "25", "43"}
    touched, unmatched, taken = 0, [], {}
    for m in data["municipalities"]:
        if m["province_code"] not in catalan_provinces or not m.get("bbox"):
            continue
        # Both registers publish the same town's extent, so the pair that overlaps best
        # IS the pair. Testing whether one centre falls inside the other polygon is not
        # enough: the cadastre publishes a bounding box, and the centre of a crescent-
        # shaped town's box lands squarely inside its neighbour (Bagà inside
        # Gisclareny), which then hands that neighbour's avalanche zones to the wrong
        # municipality.
        w, s, e, n = m["bbox"]
        x0, y0 = geo.utm_forward(s, w, zone=31)
        x1, y1 = geo.utm_forward(n, e, zone=31)
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        cat, best = None, 0.0
        for c in muni:
            iou = _box_iou(box, c["bbox"])
            if iou > best:
                cat, best = c, iou
        if best < 0.2:
            needle = fold(m["name"]).replace("la ", "").replace("el ", "").strip()
            named = next((c for c in muni
                          if fold(c["name"]).replace("la ", "").replace("el ", "").strip()
                          == needle), None)
            cat = named or cat
        if not cat:
            unmatched.append(f"{m['code']} {m['name']}")
            continue
        if cat["code"] in taken:
            unmatched.append(f"{m['code']} {m['name']} (already taken by {taken[cat['code']]})")
            continue
        taken[cat["code"]] = m["code"]
        touched += 1
        m["ine_code"] = cat["code"][:5]
        m["comarca"] = cat.get("comarca")
        m["catalan_name"] = cat.get("name")
        if cat["code"] in episodes:
            m["flood_episodes"] = episodes[cat["code"]]
        if cat["code"] in fire_rows:
            m.update(fire_rows[cat["code"]])
        if cat["code"] in zones_by_muni:
            m["avalanche_zones"] = zones_by_muni[cat["code"]]
    analysis.write(analysis.MUNICIPALITIES, data)
    log(f"catalonia: {touched} of 947 municipalities matched on the ground, "
        f"{len(zones_by_muni)} with mapped avalanche zones")
    if unmatched:
        log(f"  {len(unmatched)} cadastral towns fell outside every Catalan polygon: "
            f"{', '.join(unmatched[:5])}")


# --------------------------------------------------------------------------- #
# screen: which municipalities have any mapped flood zone at all
# --------------------------------------------------------------------------- #

HITS_RE = re.compile(r'number(?:OfFeatures|Matched)="(\d+)"')

# Enough to tell "nothing mapped here" from "something mapped here", and to order the
# something. The preferential flow zone is the severe one and T500 the most inclusive:
# a town with no T500 polygon over it has no mapped river flooding at all.
SCREEN_LAYERS = {"zfp": "agua:ZI_Laminas_ZFP", "t100": "agua:Zi_laminas_q100",
                 "t500": "agua:Zi_laminas_q500"}
# What one hit of each layer is worth when ordering which towns to look at properly.
SCREEN_WEIGHT = {"zfp": 5, "t100": 3, "t500": 1}


def screen_municipality(client: httpx.Client, muni: dict) -> dict | None:
    """How many official flood polygons touch this town, without downloading any.

    `resultType=hits` makes the WFS answer with a count and no geometry: 510 bytes and
    a tenth of a second, against the megabytes and the half minute a real query costs.
    It cannot say how many buildings are exposed - that needs the polygons and the
    cadastre - but it can say that nothing is mapped here, which for a dry inland
    village is the whole answer and is worth saying instead of "not counted yet".
    """
    bbox = muni.get("bbox")
    if not bbox:
        return None
    w, s, e, n = bbox
    out = {}
    for key, layer in SCREEN_LAYERS.items():
        params = {"service": "WFS", "version": "1.1.0", "request": "GetFeature",
                  "typeName": layer, "resultType": "hits",
                  "CQL_FILTER": f"BBOX(shape,{w},{s},{e},{n},'EPSG:4326')"}
        try:
            text = fetch(client, MITECO_WFS, params=params, pause=SCREEN_PAUSE,
                         cache=RAW / "screen" / f"{muni['code']}_{key}.xml")
        except httpx.HTTPError:
            return None
        m = HITS_RE.search(text or "")
        if not m:
            return None
        out[key] = int(m.group(1))
    return out


def build_screen(client: httpx.Client, munis: list[dict]) -> None:
    data = load_universe()
    index = {m["code"]: m for m in data["municipalities"]}
    done = empty = failed = 0
    started = time.time()
    for i, muni in enumerate(munis, start=1):
        hits = screen_municipality(client, muni)
        if hits is None:
            failed += 1
            continue
        row = index[muni["code"]]
        row["flood_screen"] = hits
        row["flood_screen_rank"] = sum(SCREEN_WEIGHT[k] * min(v, 20) for k, v in hits.items())
        done += 1
        if not row["flood_screen_rank"]:
            empty += 1
        if i % 250 == 0:
            rate = i / max(1e-9, time.time() - started)
            log(f"  {i}/{len(munis)} screened ({rate:.1f}/s, "
                f"{(len(munis) - i) / rate / 60:.0f} min left)")
            analysis.write(analysis.MUNICIPALITIES, data)  # so a stop loses little
    analysis.write(analysis.MUNICIPALITIES, data)
    log(f"screen: {done} municipalities, {empty} with nothing mapped over them, "
        f"{failed} unreachable, in {(time.time() - started) / 60:.0f} min")


# --------------------------------------------------------------------------- #
# exposure: the cadastre's buildings against the official flood zones
# --------------------------------------------------------------------------- #

FM_RE = re.compile(r"<gml:featureMember>(.*?)</gml:featureMember>", re.S)
ENVELOPE_RE = re.compile(
    r'<gml:Envelope srsName="[^"]*?(\d{5})">\s*'
    r"<gml:lowerCorner>([\d.\-]+) ([\d.\-]+)</gml:lowerCorner>\s*"
    r"<gml:upperCorner>([\d.\-]+) ([\d.\-]+)</gml:upperCorner>", re.S)
REF_RE = re.compile(r"<bu-core2d:reference>(.*?)</bu-core2d:reference>")
YEAR_RE = re.compile(r"<bu-core2d:beginning>(\d{4})")
USE_RE = re.compile(r"<bu-ext2d:currentUse>(.*?)</bu-ext2d:currentUse>")
DWELL_RE = re.compile(r"<bu-ext2d:numberOfDwellings>(\d+)</bu-ext2d:numberOfDwellings>")
UNITS_RE = re.compile(r"<bu-ext2d:numberOfBuildingUnits>(\d+)</bu-ext2d:numberOfBuildingUnits>")
AREA_RE = re.compile(r'<bu-ext2d:value uom="m2">([\d.]+)</bu-ext2d:value>')
COND_RE = re.compile(r"<bu-core2d:conditionOfConstruction>(.*?)</bu-core2d:conditionOfConstruction>")


def parse_buildings(gml: str) -> list[dict]:
    """Every building of a municipality, as a point with what the cadastre says.

    The footprint's bounding box centre stands for the building. A footprint is tens of
    metres across and the flood polygons are drawn at plot scale, so the centre is the
    honest place to ask "does this building stand in the zone"; the alternative, testing
    every vertex, would call a building exposed because a corner of its garage is.
    """
    out = []
    for block in FM_RE.findall(gml):
        env = ENVELOPE_RE.search(block)
        if not env:
            continue
        srs, x0, y0, x1, y1 = env.groups()
        zone = int(srs[-2:])  # 25830 -> 30
        lat, lon = geo.utm_inverse((float(x0) + float(x1)) / 2,
                                   (float(y0) + float(y1)) / 2, zone)
        ref = REF_RE.search(block)
        year = YEAR_RE.search(block)
        use = USE_RE.search(block)
        dwell = DWELL_RE.search(block)
        units = UNITS_RE.search(block)
        area = AREA_RE.search(block)
        cond = COND_RE.search(block)
        out.append({
            "ref": ref.group(1) if ref else None,
            "lat": round(lat, 6), "lon": round(lon, 6),
            "year": int(year.group(1)) if year else None,
            "use": (use.group(1).strip() if use and use.group(1).strip() else None),
            "dwellings": int(dwell.group(1)) if dwell else 0,
            "units": int(units.group(1)) if units else 0,
            "area_m2": float(area.group(1)) if area else None,
            "condition": cond.group(1).strip() if cond else None,
        })
    return out


def cached_buildings(code: str) -> list[dict]:
    """The municipality's buildings from the zip already on disk. Never the network."""
    path = RAW / f"bu_{code}.zip"
    if not path.exists():
        return []
    with zipfile.ZipFile(path) as zf:
        name = next((n for n in zf.namelist() if n.endswith("building.gml")), None)
        if not name:
            return []
        return parse_buildings(zf.read(name).decode("ISO-8859-1", errors="replace"))


def download_buildings(client: httpx.Client, muni: dict) -> list[dict]:
    url = muni.get("buildings_url")
    if not url:
        raise RuntimeError(f"{muni['code']}: the cadastre feed has no building download")
    blob = fetch(client, url, cache=RAW / f"bu_{muni['code']}.zip", binary=True)
    with zipfile.ZipFile(Path(RAW / f"bu_{muni['code']}.zip")) as zf:
        name = next(n for n in zf.namelist() if n.endswith("building.gml"))
        gml = zf.read(name).decode("ISO-8859-1", errors="replace")
    del blob
    return parse_buildings(gml)


def download_flood_layer(client: httpx.Client, code: str, key: str, type_name: str,
                         bbox: list[float]) -> list[list]:
    """The official polygons of one layer over the municipality's bounding box.

    The WFS answers with each feature's WHOLE geometry, which for a river that crosses
    half a province is several megabytes. That is what we want - a building on the far
    bank has to be testable - and it is why the answer is cached and the index built
    once per municipality rather than once per building.
    """
    w, s, e, n = bbox
    params = {
        "service": "WFS", "version": "1.1.0", "request": "GetFeature",
        "typeName": type_name, "outputFormat": "application/json",
        "srsName": "EPSG:4326", "maxFeatures": "400",
        "CQL_FILTER": f"BBOX(shape, {w}, {s}, {e}, {n}, 'EPSG:4326')",
    }
    text = fetch(client, MITECO_WFS, params=params,
                 cache=RAW / "flood" / f"{code}_{key}.json")
    payload = json.loads(text)
    polygons = []
    for feat in payload.get("features") or []:
        polygons.extend(spatial.rings_from_geojson(feat.get("geometry")))
    return polygons


def build_exposure(client: httpx.Client, muni: dict, *, force: bool = False) -> dict | None:
    code, name = muni["code"], muni["name"]
    target = analysis.EXPOSURE_DIR / f"{code}.json.gz"
    if target.exists() and not force:
        log(f"  {code} {name}: already built")
        return analysis.read(target)
    if not muni.get("bbox"):
        log(f"  {code} {name}: no bounding box, skipped")
        return None

    started = time.time()
    buildings = download_buildings(client, muni)
    if not buildings:
        log(f"  {code} {name}: the cadastre returned no buildings")
        return None

    indexes, edges = {}, 0
    for key, (type_name, _label) in _flood_layers().items():
        try:
            polys = download_flood_layer(client, code, key, type_name, muni["bbox"])
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log(f"  {code} {name}: {key} unavailable ({type(exc).__name__})")
            continue
        if polys:
            idx = spatial.BandIndex(polys)
            indexes[key] = idx
            edges += idx.count

    # Severity order: the worst zone a building stands in is the one that describes it.
    order = sorted(indexes, key=lambda k: -scoring.FLOOD_ZONE_SCORES.get(k, 0))
    by_zone: dict[str, int] = {}
    exposed = []
    for b in buildings:
        for key in order:
            if indexes[key].contains(b["lon"], b["lat"]):
                by_zone[key] = by_zone.get(key, 0) + 1
                exposed.append({**b, "zone": key,
                                "score": scoring.FLOOD_ZONE_SCORES.get(key)})
                break

    total = len(buildings)
    residential = [b for b in buildings if b["use"] == "1_residential"]
    exp_res = [b for b in exposed if b["use"] == "1_residential"]
    summary = scoring.score_flood_exposure(by_zone, total) or {}
    exposed.sort(key=lambda b: (-(b["score"] or 0), -(b["dwellings"] or 0)))

    # Where the town actually is. The cadastre's feed gives a bounding box, and its
    # centre is a point in a field: Murcia's municipality is 881 km2 and its box centre
    # sits in the sierra, 15 km and a climate band away from the city. Averaging the
    # homes puts the climate question where the homes are.
    homes = [b for b in buildings if b["dwellings"]]
    weight = sum(b["dwellings"] for b in homes)
    urban = ([round(sum(b["lat"] * b["dwellings"] for b in homes) / weight, 5),
              round(sum(b["lon"] * b["dwellings"] for b in homes) / weight, 5)]
             if weight else None)

    payload = {
        "version": analysis.VERSION,
        "code": code, "name": name, "province": muni["province"],
        "centroid": muni.get("centroid"), "urban_centroid": urban, "bbox": muni["bbox"],
        "buildings": {
            "total": total,
            "residential": len(residential),
            "dwellings": sum(b["dwellings"] for b in buildings),
        },
        "flood": {
            "score": summary.get("score"),
            "zone": summary.get("zone"),
            "share": summary.get("share", 0.0),
            "buildings": len(exposed),
            "residential": len(exp_res),
            "dwellings": sum(b["dwellings"] for b in exposed),
            "pre_1980": sum(1 for b in exposed if (b["year"] or 9999) < 1980),
            "by_zone": [{"zone": k, "label": _flood_layers()[k][1],
                         "score": scoring.FLOOD_ZONE_SCORES.get(k),
                         "buildings": v,
                         "dwellings": sum(b["dwellings"] for b in exposed if b["zone"] == k)}
                        for k, v in sorted(by_zone.items(),
                                           key=lambda kv: -scoring.FLOOD_ZONE_SCORES.get(kv[0], 0))],
        },
        # The list the drill-down shows. Capped: a page cannot draw forty thousand rows,
        # and the whole set stays reproducible by re-running this script.
        "exposed": exposed[:5000],
        "meta": {
            "built": dt.date.today().isoformat(),
            "cadastre_date": dt.date.today().isoformat(),
            "layers": sorted(indexes),
            "polygon_edges": edges,
            "seconds": round(time.time() - started, 1),
            "truncated": len(exposed) > 5000,
        },
    }
    analysis.write(target, payload)
    log(f"  {code} {name}: {len(exposed)}/{total} buildings in a flood zone "
        f"({payload['flood']['dwellings']} dwellings), "
        f"score {payload['flood']['score']} [{payload['meta']['seconds']}s]")
    return payload


def _flood_layers():
    from app.providers import miteco
    return miteco.LAYERS


# --------------------------------------------------------------------------- #
# assets: who and what stands in the flood zone, not just how many buildings
# --------------------------------------------------------------------------- #

def _flood_index(code: str, bbox: list[float]) -> dict:
    """The municipality's flood-zone indexes, rebuilt from the cached WFS answers.

    No network: `--only exposure` already saved every layer's polygons under
    data/analysis/raw/flood, and this reads them back so an asset is placed in a zone
    by exactly the same test the buildings went through.
    """
    indexes = {}
    for key in _flood_layers():
        path = RAW / "flood" / f"{code}_{key}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        polys = []
        for feat in payload.get("features") or []:
            polys.extend(spatial.rings_from_geojson(feat.get("geometry")))
        if polys:
            indexes[key] = spatial.BandIndex(polys)
    return indexes


PAD = 0.002  # ~200 m, so a school across the street from a flooded block is not cut off
MAX_TILES = 12  # a town is worth a dozen calls of the thousand the free tier allows


def _box(pts: list[tuple[float, float]]) -> list[float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD]


def _asset_tiles(exp: dict, max_km2: float | None) -> tuple[list[list[float]], str]:
    """The areas to ask TALAIA about: where the exposed buildings actually are.

    Not the whole municipality - Murcia's bounding box is 2,176 km², nine tenths of it
    country nobody will evacuate - but not one box around the exposed buildings either.
    A flood zone follows a river: in Zaragoza the exposed buildings are strung along
    30 km of the Ebro, so their common bounding box is 842 km² of which almost all is
    dry. Six of the thirty towns built failed the tier's 250 km² that way, Zaragoza and
    Murcia among them, which are the two with the most homes at risk.

    So the extent is cut into a grid fine enough for one cell to fit the limit, and only
    the cells that actually hold exposed buildings are asked about, each tightened to
    the buildings inside it. A river corridor becomes a handful of small boxes and the
    dry ground between them is never sent.
    """
    pts = [(b["lon"], b["lat"]) for b in (exp.get("exposed") or [])]
    if not pts:
        return [exp["bbox"]], "municipality"

    full = _box(pts)
    area = spatial.haversine_area_km2(tuple(full))
    if not max_km2 or area <= max_km2:
        return [full], "flooded area"

    # A grid whose cell is comfortably inside the limit, then only the busy cells.
    steps = math.ceil(math.sqrt(area / (max_km2 * 0.6)))
    w = (full[2] - full[0]) / steps
    h = (full[3] - full[1]) / steps
    cells: dict[tuple[int, int], list] = {}
    for x, y in pts:
        key = (min(steps - 1, int((x - full[0]) / w)) if w else 0,
               min(steps - 1, int((y - full[1]) / h)) if h else 0)
        cells.setdefault(key, []).append((x, y))

    tiles = [_box(v) for _, v in sorted(cells.items(), key=lambda kv: -len(kv[1]))]
    tiles = [t for t in tiles if spatial.haversine_area_km2(tuple(t)) <= max_km2]
    return tiles[:MAX_TILES], f"flooded area in {min(len(tiles), MAX_TILES)} parts"


def build_assets(codes: list[str], *, force: bool = False) -> None:
    """Add the inventory of people, institutions and value to each exposure on disk."""
    import asyncio

    from app.providers import talaia

    if not talaia.available():
        log("assets: TALAIA_API_KEY is not set, so nothing was asked and nothing was "
            "invented. Set it in .env and re-run --only assets.")
        return

    who = asyncio.run(talaia.whoami())
    limits = asyncio.run(talaia.tiers())
    tier = who.get("tier") if who.get("ok") else None
    max_km2 = next((float(t["max_aoi_km2"]) for t in (limits.get("tiers") or [])
                    if t["name"] == tier and isinstance(t.get("max_aoi_km2"), (int, float))),
                   None)
    if not who.get("ok"):
        log(f"assets: the key was refused ({who.get('error')}), nothing was asked")
        return
    log(f"assets: key on tier '{tier}'"
        + (f", up to {max_km2:.0f} km2 per call" if max_km2 else ""))

    done = skipped = 0
    for code in codes:
        exp = analysis.read(analysis.EXPOSURE_DIR / f"{code}.json.gz")
        if not exp:
            continue
        if exp.get("assets") and not force:
            log(f"  {code} {exp['name']}: already asked")
            continue

        tiles, what = _asset_tiles(exp, max_km2)
        area = sum(spatial.haversine_area_km2(tuple(t)) for t in tiles)
        if not tiles:
            exp["assets"] = {"available": False, "aoi_km2": 0.0,
                             "reason": "the flooded area could not be cut into parts "
                                       f"inside the {max_km2:.0f} km2 the '{tier}' "
                                       "tier allows"}
            analysis.write(analysis.EXPOSURE_DIR / f"{code}.json.gz", exp)
            log(f"  {code} {exp['name']}: cannot fit the tier limit, skipped")
            skipped += 1
            continue

        parts, failed = [], []
        for tile in tiles:
            part = asyncio.run(talaia.exposure(
                talaia.bbox_polygon(tile), population_grid=True,
                cache_key=f"{code}:{tile}:grid"))
            if part.get("ok"):
                parts.append(part)
            else:
                failed.append(str(part.get("error"))[:120])
        if not parts:
            log(f"  {code} {exp['name']}: {failed[0] if failed else 'no answer'}")
            skipped += 1
            continue

        report = _merge_reports(parts)
        if failed:
            report["warnings"].append(
                f"{len(failed)} of {len(tiles)} parts failed: {failed[0]}")
        cells = ((report.get("population") or {}).get("cells")) or []
        exp["assets"] = _asset_block(code, exp, report, tiles, what, area,
                                     _residents_in_zone(code, exp, cells))
        analysis.write(analysis.EXPOSURE_DIR / f"{code}.json.gz", exp)
        a = exp["assets"]
        zone_pop = a.get("population_in_zone")
        log(f"  {code} {exp['name']}: {a['count']} assets, "
            f"{a['in_flood_zone']['count']} of them inside a flood zone "
            f"({a['in_flood_zone']['people']:.0f} people at capacity); "
            + (f"{zone_pop:,} residents on the ground that floods"
               if zone_pop is not None else
               f"{a['population_area']:,.0f} residents in the area asked about, "
               "not apportioned"))
        done += 1
    log(f"assets: {done} municipalities, {skipped} skipped")


def _residents_in_zone(code: str, exp: dict, cells: list[dict]) -> dict | None:
    """The residents of the ground that floods, not of the area we happened to ask about.

    TALAIA's population total is the census grid weighted to the AOI, and the AOI is a
    box (or a few) around the exposed buildings. For a flood zone that follows a river
    through a city those boxes cover most of the city: València came back with 938,408
    residents "at risk" next to 1,101 flooded dwellings, which is the population of
    València. The total is right for what it measures and wrong for what the column
    claims.

    So each 1 km census cell is apportioned by the dwellings inside it: what share of
    that cell's homes stand in a flood zone. The cadastre has every building of the
    municipality with its coordinates and its dwelling count, and it is already on disk,
    so this costs nothing but the read.

        residents in zone = SUM over cells of  population * exposed dwellings
                                               ------------------------------
                                               all dwellings in the same cell

    It assumes people are spread across a cell the way dwellings are, which is the
    standard dasymetric assumption and is the reason the figure is reported as an
    estimate. Where a cell has census population but no cadastral dwellings at all
    (Basque enclaves, bad geometry) it contributes nothing rather than everything.
    """
    buildings = cached_buildings(code)
    if not buildings or not cells:
        return None

    # One cell size for the whole town - they are all at the same latitude - so a
    # building can be put in its cell by arithmetic instead of a scan. The lattice is
    # anchored on a real cell centroid: the INE grid is regular in metres (EPSG:3035),
    # not in degrees, so a lattice starting from zero sits offset from it and drops
    # buildings near the cell edges into cells that were never returned. Anchoring
    # takes València from 97.8 % of its dwellings landing in a cell to 99.1 %.
    step = math.sqrt(max(0.25, min(4.0, float(cells[0].get("area_km2") or 1.0))))
    mid = sum(c["lat"] for c in cells) / len(cells)
    dlat = step / 110.574
    dlon = step / (111.320 * max(0.2, math.cos(math.radians(mid))))
    lat0 = min(c["lat"] for c in cells)
    lon0 = min(c["lon"] for c in cells)
    key = lambda lat, lon: (round((lat - lat0) / dlat),  # noqa: E731
                            round((lon - lon0) / dlon))

    grid = {key(c["lat"], c["lon"]): {"cell": c, "all": 0.0, "exposed": 0.0}
            for c in cells}

    exposed_refs = {b["ref"] for b in (exp.get("exposed") or []) if b.get("ref")}
    for b in buildings:
        dw = float(b.get("dwellings") or 0)
        slot = grid.get(key(b["lat"], b["lon"])) if dw else None
        if slot is None:
            continue
        slot["all"] += dw
        if b["ref"] in exposed_refs:
            slot["exposed"] += dw

    # People per dwelling, cell by cell, and the town's own figure from the cells big
    # enough to be trusted. A 1 km cell straddles the municipal boundary, and the
    # neighbours' residents are in its census count while their buildings are not in
    # this town's cadastre: València has cells with 4,693 residents and 14 cadastral
    # dwellings, which apportions to 335 people per home. The cell's ratio is therefore
    # only believed within a factor of two of the town's own, and outside that the
    # town's figure is used. Paiporta and Zaragoza, whose cells are all sane, are
    # untouched by the clamp; València stops claiming 13 people per flooded dwelling.
    ratios = sorted(float(s["cell"].get("population") or 0) / s["all"]
                    for s in grid.values() if s["all"] >= 50)
    # The town's figure is itself held to a plausible household: a municipality of two
    # square kilometres (Massanassa, Sedaví) has NO uncontaminated cell - every one of
    # its 1 km squares reaches into a denser neighbour - so its median comes out at six
    # people per home and the per-cell clamp, measured against that median, lets it
    # through. INE's average household is 2.5; anything outside 1.5 to 3.0 is the
    # boundary, not the town. Where the clamp binds, the figure is an upper bound and
    # `persons_per_dwelling` in the output says so.
    town_ppd = ratios[len(ratios) // 2] if ratios else 2.5
    town_ppd = min(max(town_ppd, 1.5), 3.0)
    # And the cell's own figure never leaves the plausible band either. Bounding the
    # cell at twice the town's alone was not enough: Massanassa's median is pinned at
    # the town ceiling of 3.0 and twice that is six people to a flat. Nothing in Spain
    # averages more than three.
    lo, hi = max(1.0, town_ppd * 0.5), min(3.0, town_ppd * 2.0)

    residents = 0.0
    counted = clamped = 0
    for slot in grid.values():
        if slot["all"] <= 0 or slot["exposed"] <= 0:
            continue
        ppd = float(slot["cell"].get("population") or 0) / slot["all"]
        if not lo <= ppd <= hi:
            clamped += 1
            ppd = min(max(ppd, lo), hi)
        residents += slot["exposed"] * ppd
        counted += 1

    dwellings = exp["flood"]["dwellings"] or 0
    return {"residents": round(residents),
            "cells_with_flooded_homes": counted,
            "cells_in_area": len(grid),
            "cells_clamped": clamped,
            "persons_per_dwelling": round(residents / dwellings, 2) if dwellings else None,
            "town_persons_per_dwelling": round(town_ppd, 2),
            "method": "1 km INE census cells apportioned by the share of each cell's "
                      "cadastral dwellings that stand in a flood zone, with each "
                      "cell's people-per-dwelling held within a factor of two of the "
                      "municipality's own"}


SUMMABLE = ("asset_count", "people_estimate", "people_from_registry",
            "people_from_defaults", "population_resident", "total_value_eur",
            "critical_assets", "hazardous_assets", "response_assets", "livestock_units")


def _merge_reports(parts: list[dict]) -> dict:
    """Several tiles of one town read as one report.

    One tile is passed through untouched. Several are added up, with one rule: an asset
    that arrives twice - a site on a tile edge, returned by both - is dropped on its
    name, position and kind, and every total that can be derived from the assets is
    then recomputed from the deduplicated list rather than summed from the tiles' own
    summaries. Summing them would leave the school counted once in the list and twice
    in the category breakdown, and a breakdown that disagrees with the list beside it
    is worse than no breakdown.

    Only the resident population is summed, because it comes from the census grid
    apportioned to each tile and the tiles do not overlap.
    """
    if len(parts) == 1:
        p = parts[0]
        return {"summary": p.get("summary") or {}, "assets": p.get("assets") or [],
                "assets_truncated": bool(p.get("assets_truncated")),
                "population": p.get("population") or {},
                "sources": p.get("sources") or [], "warnings": list(p.get("warnings") or []),
                "generated_at": p.get("generated_at")}

    assets, seen, sources, warnings = [], set(), [], []
    cells: dict[str, dict] = {}
    population = 0.0
    truncated = False
    for part in parts:
        population += float((part.get("summary") or {}).get("population_resident") or 0)
        # A 1 km census cell can touch two tiles. Keep it once, with the whole-cell
        # population: the apportionment below divides it by the cell's own dwellings,
        # so a cell counted twice would count its residents twice.
        for cell in ((part.get("population") or {}).get("cells") or []):
            cells.setdefault(cell.get("cell_id") or f"{cell['lat']},{cell['lon']}", cell)
        for asset in part.get("assets") or []:
            key = (asset.get("name"), round(asset.get("lat") or 0, 6),
                   round(asset.get("lon") or 0, 6), asset.get("subcategory"))
            if key in seen:
                continue
            seen.add(key)
            assets.append(asset)
        truncated = truncated or bool(part.get("assets_truncated"))
        sources.extend(part.get("sources") or [])
        warnings.extend(part.get("warnings") or [])

    def num(asset, *path):
        node = asset
        for step in path:
            node = (node or {}).get(step)
        return float(node or 0)

    by_category: dict[str, dict] = {}
    for a in assets:
        cat = a.get("category") or "other"
        row = by_category.setdefault(cat, {"category": cat, "label": cat.title(),
                                           "count": 0, "people_estimate": 0.0,
                                           "total_value_eur": 0.0,
                                           "human_bearing": False})
        row["count"] += 1
        row["people_estimate"] += num(a, "capacity", "people")
        row["total_value_eur"] += num(a, "valuation", "total_eur")
        row["human_bearing"] = row["human_bearing"] or bool(a.get("human_bearing"))

    summary = {
        "asset_count": len(assets),
        "people_estimate": sum(num(a, "capacity", "people") for a in assets),
        "population_resident": population,
        "total_value_eur": sum(num(a, "valuation", "total_eur") for a in assets),
        "livestock_units": sum(num(a, "capacity", "livestock_units") for a in assets),
        "critical_assets": sum(1 for a in assets if a.get("criticality", 0) >= 80),
        "hazardous_assets": sum(1 for a in assets if a.get("hazardous")),
        "response_assets": sum(1 for a in assets if a.get("response_asset")),
        "by_category": sorted(by_category.values(), key=lambda c: -c["count"]),
    }
    return {"summary": summary, "assets": assets, "assets_truncated": truncated,
            "population": {"cells": list(cells.values()), "total": population},
            "sources": sources, "warnings": warnings,
            "generated_at": parts[0].get("generated_at")}


# What an institution is called out for: a school, a care home, a hospital, a campsite.
# `hazardous` and `response` come from TALAIA's own flags.
def _asset_block(code: str, exp: dict, report: dict, tiles: list, what: str,
                 area: float, apportioned: dict | None = None) -> dict:
    summary = report.get("summary") or {}
    indexes = _flood_index(code, exp["bbox"])
    order = sorted(indexes, key=lambda k: -scoring.FLOOD_ZONE_SCORES.get(k, 0))

    items, by_zone = [], {}
    inside_people = inside_value = 0.0
    for asset in report.get("assets") or []:
        lat, lon = asset.get("lat"), asset.get("lon")
        zone = None
        if lat is not None and lon is not None:
            zone = next((k for k in order if indexes[k].contains(lon, lat)), None)
        capacity = asset.get("capacity") or {}
        valuation = asset.get("valuation") or {}
        row = {
            "name": asset.get("name"),
            "category": asset.get("category"),
            "subcategory": asset.get("subcategory"),
            "lat": lat, "lon": lon,
            "people": capacity.get("people"),
            "beds": capacity.get("beds"),
            "students": capacity.get("students"),
            "livestock_units": capacity.get("livestock_units"),
            "value_eur": valuation.get("total_eur"),
            "hazardous": bool(asset.get("hazardous")),
            "response": bool(asset.get("response_asset")),
            "human_bearing": bool(asset.get("human_bearing")),
            "zone": zone,
        }
        items.append(row)
        if zone:
            by_zone[zone] = by_zone.get(zone, 0) + 1
            inside_people += float(row["people"] or 0)
            inside_value += float(row["value_eur"] or 0)

    inside = [i for i in items if i["zone"]]
    # Worst zone first, then the ones that hold people, then the biggest.
    rank = {k: -scoring.FLOOD_ZONE_SCORES.get(k, 0) for k in scoring.FLOOD_ZONE_SCORES}
    inside.sort(key=lambda i: (rank.get(i["zone"], 0), not i["human_bearing"],
                               -(i["people"] or 0)))

    return {
        "available": True,
        "aoi": {"parts": tiles, "covers": what, "km2": round(area, 1)},
        "count": summary.get("asset_count") or len(items),
        # Two different questions, kept apart on purpose: how many people live in the
        # area asked about, and how many live on the ground that floods.
        "population_area": float(summary.get("population_resident") or 0),
        "population_in_zone": (apportioned or {}).get("residents"),
        "population_method": (apportioned or {}).get("method"),
        "population_cells": (apportioned or {}).get("cells_with_flooded_homes"),
        # Kept so the estimate can be argued with: how many people the figure implies
        # per flooded dwelling, and how many cells needed their ratio held in band.
        "persons_per_dwelling": (apportioned or {}).get("persons_per_dwelling"),
        "population_cells_clamped": (apportioned or {}).get("cells_clamped"),
        "people_estimate": float(summary.get("people_estimate") or 0),
        "people_from_registry": float(summary.get("people_from_registry") or 0),
        "total_value_eur": float(summary.get("total_value_eur") or 0),
        "critical": summary.get("critical_assets") or 0,
        "hazardous": summary.get("hazardous_assets") or 0,
        "response": summary.get("response_assets") or 0,
        "livestock_units": float(summary.get("livestock_units") or 0),
        "by_category": summary.get("by_category") or [],
        "in_flood_zone": {
            "count": len(inside),
            "people": round(inside_people, 1),
            "value_eur": round(inside_value, 0),
            "by_zone": [{"zone": k, "count": v} for k, v in
                        sorted(by_zone.items(),
                               key=lambda kv: -scoring.FLOOD_ZONE_SCORES.get(kv[0], 0))],
            # The list an emergency service reads: named, with its zone and its people.
            "items": [i for i in inside if i["human_bearing"] or i["hazardous"]][:200],
        },
        "truncated": bool(report.get("assets_truncated")),
        "warnings": report.get("warnings") or [],
        "sources": [s.get("id") or s.get("name") for s in (report.get("sources") or [])][:40],
        "generated_at": report.get("generated_at"),
    }


# --------------------------------------------------------------------------- #
# heat: ERA5, for the municipalities we can afford
# --------------------------------------------------------------------------- #

def build_heat(codes: list[str]) -> None:
    """Days a year at 35 °C or more, from the same ERA5 series a report uses.

    Open-Meteo's free tier is capped per day, so this stops at the first quota error.
    What it did not reach keeps no value at all, which is the honest outcome: the
    ranking then says heat is missing for that town instead of implying a low one.
    """
    import asyncio

    from app import series as S
    from app.providers import open_meteo

    data = load_universe()
    index = {m["code"]: m for m in data["municipalities"]}
    done, stopped = 0, None

    async def one(muni: dict) -> bool:
        lat, lon = muni["centroid"]
        payload = await open_meteo.fetch_archive(lat, lon)
        full = S.DailySeries.from_open_meteo(payload)
        recent = full.subset(min_year=config.CLIMATOLOGY_START)
        days = S.per_year(S.frequency(recent, "temperature_2m_max", lambda v: v >= 35))
        if days is None:
            return False
        muni["heat_days_35"] = round(days, 1)
        return True

    for code in codes:
        muni = index.get(code)
        if not muni or not muni.get("centroid"):
            continue
        try:
            if asyncio.run(one(muni)):
                done += 1
                log(f"  {code} {muni['name']}: {muni['heat_days_35']} days a year at 35 °C")
        except Exception as exc:  # the quota answers 429 through several exception types
            stopped = f"{type(exc).__name__}: {exc}"
            log(f"  stopped at {code} {muni['name']}: {stopped}")
            break

    data.setdefault("notes", {})["heat"] = {
        "built_for": done, "requested": len(codes), "stopped_at": stopped,
        "why": "ERA5 comes from Open-Meteo's free tier, which caps requests per day",
    }
    analysis.write(analysis.MUNICIPALITIES, data)
    log(f"heat: {done} of {len(codes)} municipalities")


# --------------------------------------------------------------------------- #
# ranking: assemble what the others left on disk
# --------------------------------------------------------------------------- #

def build_ranking() -> dict:
    data = load_universe()
    grid = cds_layers.fire_data()
    rows = []
    for m in data["municipalities"]:
        exp = analysis.read(analysis.EXPOSURE_DIR / f"{m['code']}.json.gz")
        if exp:
            exp = _rescore(m["code"], exp)
        metrics = dict(m)
        centroid = m.get("centroid")
        # Where the buildings are known, read the climate over the town rather than over
        # the middle of its bounding box (see build_exposure).
        if exp and exp.get("urban_centroid") and grid:
            centroid = exp["urban_centroid"]
            proj = cds_layers.fire_projection(centroid[0], centroid[1], grid) or {}
            days = (proj.get("historical_1981_2005") or {}).get("high")
            if days is not None:
                metrics["fire_weather_days"] = round(days, 1)
                fut = (proj.get("rcp8_5_2041_2060") or {}).get("high")
                metrics["fire_weather_2050"] = round(fut, 1) if fut is not None else None
                metrics["fire_weather_context"] = (
                    f"{fut - days:+.0f} days a year by 2041-2060 under RCP8.5"
                    if fut is not None else None)
        m = metrics
        scores = {
            "fire_weather": scoring.score_for("fire_weather_fwi", m.get("fire_weather_days")),
            "flood": (exp or {}).get("flood", {}).get("score"),
            "flood_history": scoring.score_for("flood_history", m.get("flood_episodes")),
            "fire_history": scoring.score_for("burnt_area_municipal", m.get("burnt_ha")),
            "avalanche": _avalanche_score(m.get("avalanche_zones")),
            "heat": scoring.score_for("heat", m.get("heat_days_35")),
        }
        scores["overall"] = scoring.aggregate([v for v in scores.values() if v is not None])
        row = {
            # The cadastre writes many Catalan names without their accents ("Llado");
            # where the Catalan register gave us the town's own spelling, use it.
            "code": m["code"], "name": m.get("catalan_name") or m["name"],
            "ine_code": m.get("ine_code"),
            "province": m["province"], "province_code": m["province_code"],
            "comarca": m.get("comarca"),
            "centroid": centroid,
            # What the cheap screen found: how many official flood polygons touch the
            # town. Zero is an answer - "nothing is mapped here" - and the page says
            # that instead of "not counted yet", which reads like an omission.
            "flood_screen": m.get("flood_screen"),
            "flood_screen_rank": m.get("flood_screen_rank"),
            "scores": {k: v for k, v in scores.items()},
            "metrics": {k: m.get(k) for k in
                        ("fire_weather_days", "fire_weather_2050", "fire_weather_context",
                         "flood_episodes", "fires_count", "burnt_ha", "avalanche_zones",
                         "heat_days_35") if m.get(k) is not None},
        }
        if exp:
            row["exposure"] = {
                "buildings": exp["buildings"]["total"],
                "dwellings": exp["buildings"]["dwellings"],
                "flooded_buildings": exp["flood"]["buildings"],
                "flooded_dwellings": exp["flood"]["dwellings"],
                "worst_zone": exp["flood"]["zone"],
                "share": exp["flood"]["share"],
            }
            # What an institution actually plans around: not a score, a number of homes.
            row["homes_at_risk"] = exp["flood"]["dwellings"]
            assets = exp.get("assets") or {}
            if assets.get("available"):
                inside = assets["in_flood_zone"]
                row["exposure"].update({
                    "population": assets.get("population_in_zone"),
                    "population_area": assets.get("population_area"),
                    "institutions": inside["count"],
                    "institution_people": inside["people"],
                    "value_eur": inside["value_eur"],
                    "hazardous": assets["hazardous"],
                })
                # Residents of the ground that floods, apportioned from the census
                # grid by where the flooded dwellings are. NOT the population of the
                # area we asked about, which for a river through a city is the city.
                if assets.get("population_in_zone") is not None:
                    row["people_at_risk"] = round(assets["population_in_zone"])
        rows.append(row)

    payload = {
        "version": analysis.VERSION,
        "meta": {
            "built": dt.date.today().isoformat(),
            "municipalities": len(rows),
            "with_exposure": sum(1 for r in rows if r.get("exposure")),
            "with_assets": sum(1 for r in rows if r.get("people_at_risk") is not None),
            "screened": sum(1 for r in rows if r.get("flood_screen") is not None),
            "screened_dry": sum(1 for r in rows if r.get("flood_screen_rank") == 0),
            "with_climate": sum(1 for r in rows if r["scores"]["fire_weather"] is not None),
            "with_heat": sum(1 for r in rows if r["scores"]["heat"] is not None),
            "not_covered": data.get("not_covered"),
            "scales": {k: scoring.explain_breakpoints(v) for k, v in
                       (("fire_weather", "fire_weather_fwi"), ("heat", "heat"),
                        ("flood_history", "flood_history"),
                        ("fire_history", "fire_history"))},
        },
        "provinces": data.get("provinces", []),
        "rows": rows,
    }
    analysis.write(analysis.RANKING, payload)
    analysis.reload()
    log(f"ranking: {len(rows)} municipalities, "
        f"{payload['meta']['with_exposure']} with building exposure "
        f"-> {analysis.RANKING.name}")
    return payload


def _rescore(code: str, exp: dict) -> dict:
    """Apply today's flood scale to an exposure built earlier.

    Crossing the buildings with the flood zones costs a minute and several megabytes;
    turning the counts it produced into a score costs nothing. So the counts are the
    thing kept on disk, and the score is recomputed from them on every assembly - a
    change to the scale in scoring.py reaches every municipality without downloading
    anything again.
    """
    counts = {z["zone"]: z["buildings"] for z in exp["flood"]["by_zone"]}
    summary = scoring.score_flood_exposure(counts, exp["buildings"]["total"]) or {}
    if summary.get("score") == exp["flood"].get("score"):
        return exp
    exp["flood"].update({"score": summary.get("score"), "zone": summary.get("zone"),
                         "share": summary.get("share", 0.0)})
    analysis.write(analysis.EXPOSURE_DIR / f"{code}.json.gz", exp)
    return exp


def _avalanche_score(zones: int | None) -> float | None:
    """A municipality with mapped avalanche paths, scaled by how many of them.

    The report scores a point against the path it stands in. A municipality cannot be
    scored that way, so this only says how much avalanche terrain the ICGC mapped
    inside it, and it never reaches the score a mapped path gives a house.
    """
    if not zones:
        return None
    return scoring.interpolate(zones, [(0, 0), (1, 30), (10, 50), (50, 65), (200, 75)])


# --------------------------------------------------------------------------- #

def pick(args, data: dict) -> list[dict]:
    """Which municipalities a run of --only exposure should cover.

    `--top N` means N municipalities that do not have one yet, not the N highest of
    which thirty are already on disk: the point of a second run is to widen the
    coverage. `--force` puts the built ones back in, to apply a change to the parser.

    `--per-province` takes that many from EACH province instead of N overall, which is
    how you get a ranking that covers the country without the two days and 0.7 TB a
    full crawl of all 7,597 would take.

    The order is the screen (`--only screen`) where it has run: how many official flood
    polygons touch the town, weighted by severity. Before the screen, the only order
    available is the overall score, which is driven by fire weather - a poor way to
    choose where to look for flooding, and the build says so.
    """
    munis = data["municipalities"]
    if args.municipality:
        wanted = set(args.municipality)
        return [m for m in munis if m["code"] in wanted]
    if args.province:
        munis = [m for m in munis if m["province_code"] == args.province]
    if not args.force:
        munis = [m for m in munis
                 if not (analysis.EXPOSURE_DIR / f"{m['code']}.json.gz").exists()]

    screened = sum(1 for m in munis if m.get("flood_screen_rank") is not None)
    if screened:
        # Nothing mapped over the town means nothing to count: skip it outright.
        munis = [m for m in munis if m.get("flood_screen_rank", 1) > 0]
        # The rank saturates: each layer counts at most 20 polygons, so a town covered
        # by a river system and one covered by three of them both reach the ceiling.
        # Ties are broken by name, which decides nothing but makes the run repeatable.
        order = lambda m: (-(m.get("flood_screen_rank") or 0), m["name"])  # noqa: E731
    else:
        log("  no screen on disk: ordering by the overall score, which is mostly fire "
            "weather. Run --only screen first to choose by mapped flood risk.")
        ranked = analysis.read(analysis.RANKING) or {"rows": []}
        scores = {r["code"]: r["scores"].get("overall") or 0 for r in ranked["rows"]}
        order = lambda m: -scores.get(m["code"], 0)  # noqa: E731

    munis = sorted(munis, key=order)
    if args.per_province:
        out, seen = [], {}
        for m in munis:
            pp = m["province_code"]
            if seen.get(pp, 0) >= args.per_province:
                continue
            seen[pp] = seen.get(pp, 0) + 1
            out.append(m)
        return out
    return munis[:args.top]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=["universe", "climate", "catalonia", "screen",
                                      "exposure", "assets", "heat", "ranking"],
                   action="append")
    p.add_argument("--municipality", action="append",
                   help="cadastral code, e.g. 46188 (Paiporta). Repeatable.")
    p.add_argument("--province", help="two-digit province code, e.g. 46")
    p.add_argument("--top", type=int, default=10,
                   help="how many municipalities --only exposure covers (default 10)")
    p.add_argument("--per-province", type=int, default=None,
                   help="take this many from EACH province instead of --top overall")
    p.add_argument("--force", action="store_true", help="rebuild what is already on disk")
    args = p.parse_args()

    steps = args.only or ["universe", "climate", "catalonia", "exposure", "assets",
                          "ranking"]
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        if "universe" in steps:
            build_universe(client)
        if "climate" in steps:
            build_climate()
        if "catalonia" in steps:
            build_catalonia()
        if "screen" in steps:
            data = load_universe()
            todo = [m for m in data["municipalities"]
                    if m.get("bbox") and (args.force or m.get("flood_screen") is None)]
            if args.province:
                todo = [m for m in todo if m["province_code"] == args.province]
            log(f"screen: {len(todo)} municipalities to ask MITECO about "
                f"(counts only, no geometry)")
            build_screen(client, todo)
        if "exposure" in steps:
            data = load_universe()
            chosen = pick(args, data)
            log(f"exposure: {len(chosen)} municipalities")
            for muni in chosen:
                try:
                    build_exposure(client, muni, force=args.force)
                except Exception as exc:
                    log(f"  {muni['code']} {muni['name']}: failed "
                        f"({type(exc).__name__}: {exc})")
        if "assets" in steps:
            # Only where the buildings are already counted: the area asked about is the
            # box around them, and without them there is nothing to place in a zone.
            built = sorted(f.name[:-8] for f in analysis.EXPOSURE_DIR.glob("*.json.gz"))
            codes = args.municipality or built
            log(f"assets: {len(codes)} municipalities with an exposure on disk")
            build_assets(codes, force=args.force)
        if "heat" in steps:
            data = load_universe()
            codes = args.municipality or [m["code"] for m in pick(args, data)]
            build_heat(codes)
        if "ranking" in steps:
            build_ranking()


if __name__ == "__main__":
    main()
