"""Downloads and prepares the Catalan batch layer.

Everything that changes little is downloaded once and queried locally:

  municipalities.json.gz   947 municipalities (polygons, AGORA/UB)     -> point -> municipality
  agora_episodes.json.gz   228 flood episodes 1902-2020 (UB)           -> history
  fire_perimeters.json.gz  wildfire perimeters 1986-2024 (Gencat)      -> distance to fires
  fire_stats.json.gz       fires by municipality 2011-today (Socrata)  -> municipal statistics
  avalanches.json.gz       ICGC avalanche zones, observed and surveyed
                           avalanches, snow-climate zones (WFS)        -> avalanche card
  manifest.json            provenance, download dates and counts

What is queried live (MITECO flood zones, ICGC sea-level rise) does NOT go through here:
it lives in app/providers/.

    python backend/scripts/catalonia_build.py
    python backend/scripts/catalonia_build.py --only fires     # a single block

It can be resumed: raw downloads are kept in data/catalonia/raw/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import sys
import time
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import httpx  # noqa: E402

from app import config, geo  # noqa: E402

OUT = config.CATALONIA_DIR
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

AGORA = ("https://services-eu1.arcgis.com/cBVVvOe2P4c5pIi3/arcgis/rest/services/"
         "AGORAPublico/FeatureServer")
FIRES_PAGE = ("https://agricultura.gencat.cat/ca/serveis/cartografia-sig/bases-cartografiques/"
              "boscos/incendis-forestals/incendis-forestals-format-shp/")
SOCRATA = "https://analisi.transparenciacatalunya.cat/resource/{id}.json"
SOCRATA_FIRES = {"bks7-dkfd": "2011-2024", "crs7-idxi": "previous year", "9r29-e8ha": "current year"}
# ICGC's avalanche GeoServer (the "WMS Allaus" service also answers WFS).
NIVO_WFS = "https://geoserveis.icgc.cat/geoserver/nivoallaus/wfs"

HTTP = httpx.Client(timeout=120, follow_redirects=True,
                    headers={"User-Agent": config.USER_AGENT})


def write_gz(name: str, payload) -> Path:
    path = OUT / name
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return path


def norm_muni(code) -> str | None:
    """6-digit INE code (province + municipality + check digit).

    Socrata drops Barcelona's leading zero ("80898"); AGORA does not ("171609").
    Without normalising, no municipality in the province of Barcelona would match.
    """
    if code is None:
        return None
    digits = re.sub(r"\D", "", str(code))
    return digits.zfill(6) if digits else None


def epoch_ms_to_date(value) -> str | None:
    """ISO date from milliseconds, dates before 1970 included (AGORA starts in 1902, and
    `datetime.fromtimestamp` fails on Windows with negative epochs)."""
    if not isinstance(value, (int, float)):
        return None
    return (dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=value)).date().isoformat()


# --------------------------------------------------------------------------- #
# AGORA: municipalities and flood episodes
# --------------------------------------------------------------------------- #
def arcgis_all(layer: int, **params) -> list[dict]:
    """Downloads every row of a layer, paginating (maxRecordCount = 2000)."""
    rows, offset = [], 0
    while True:
        q = {"where": "1=1", "outFields": "*", "f": "json",
             "resultOffset": offset, "resultRecordCount": 2000, **params}
        data = HTTP.get(f"{AGORA}/{layer}/query", params=q).json()
        if "error" in data:
            raise RuntimeError(f"AGORA layer {layer}: {data['error']}")
        feats = data.get("features", [])
        rows.extend(feats)
        if not data.get("exceededTransferLimit") or not feats:
            return rows
        offset += len(feats)


def build_agora() -> dict:
    print("AGORA · municipalities (polygons in EPSG:25831)")
    munis = arcgis_all(1, outSR=25831, returnGeometry="true",
                       geometryPrecision=0, maxAllowableOffset=20,
                       outFields="CODIMUNI,NOMMUNI,NOMCOMAR,NOMPROV")
    municipalities = []
    for f in munis:
        rings = [[(float(x), float(y)) for x, y in ring]
                 for ring in (f.get("geometry") or {}).get("rings", [])]
        if not rings:
            continue
        polygons = group_rings(rings)
        a = f["attributes"]
        municipalities.append({
            "code": norm_muni(a.get("CODIMUNI")),
            "name": a.get("NOMMUNI"),
            "comarca": a.get("NOMCOMAR"),
            "province": a.get("NOMPROV"),
            "bbox": [round(v) for v in geo.bbox_of(polygons)],
            "polygons": [[[[round(x), round(y)] for x, y in ring] for ring in rings_]
                         for rings_ in polygons],
        })
    write_gz("municipalities.json.gz", municipalities)
    print(f"   {len(municipalities)} municipalities")

    print("AGORA · episodes and their link to municipalities")
    episodes = {}
    for f in arcgis_all(4):
        a = f["attributes"]
        episodes[str(a["EPISODI"])] = {
            "id": str(a["EPISODI"]),
            "start": epoch_ms_to_date(a.get("INICI_EPISODI")),
            "end": epoch_ms_to_date(a.get("FINAL_EPISODI")),
            "phenomena": a.get("FENOMENSMETEO"),
            "category": a.get("CATEGORIA"),
            "victims": a.get("VICTIMES"),
            "losses_raw": a.get("PERDIDAS_EUROS"),
            "damage": a.get("DESC_DANYS"),
            "report_url": a.get("ENLAC_INFORME"),
            "municipalities_text": a.get("MUNICIPIS_AF"),
        }
    by_muni = defaultdict(list)
    for f in arcgis_all(5, outFields="CODIMUNI,EPISODI", returnGeometry="false"):
        a = f["attributes"]
        code, ep = norm_muni(a.get("CODIMUNI")), str(a.get("EPISODI"))
        if code and ep in episodes and ep not in by_muni[code]:
            by_muni[code].append(ep)
    starts = sorted(e["start"] for e in episodes.values() if e["start"])
    write_gz("agora_episodes.json.gz", {"episodes": episodes, "by_municipality": by_muni})
    print(f"   {len(episodes)} episodes ({starts[0]} → {starts[-1]}), "
          f"{sum(len(v) for v in by_muni.values())} links to {len(by_muni)} municipalities")
    return {
        "municipalities": len(municipalities),
        "episodes": len(episodes),
        "episodes_period": f"{starts[0][:4]}-{starts[-1][:4]}",
        "episodes_first": starts[0],
        "episodes_last": starts[-1],
    }


def group_rings(rings: list[list[tuple[float, float]]]) -> list[list[list[tuple[float, float]]]]:
    """Groups loose rings into polygons (exterior + holes).

    Shapefile and Esri JSON mark the exterior clockwise and the holes
    anticlockwise. In the shoelace formula with the Y axis pointing up,
    clockwise gives a negative area. Each hole is assigned to the exterior that
    contains it.
    """
    def signed(ring):
        s = 0.0
        for i in range(len(ring)):
            x1, y1 = ring[i - 1]
            x2, y2 = ring[i]
            s += x1 * y2 - x2 * y1
        return s / 2

    outers, holes = [], []
    for ring in rings:
        if len(ring) < 4:
            continue
        (outers if signed(ring) < 0 else holes).append(ring)
    if not outers:  # non-standard orientation: everything is treated as exteriors
        return [[r] for r in rings if len(r) >= 4]
    polygons = [[o] for o in outers]
    for hole in holes:
        hx, hy = hole[0]
        for poly in polygons:
            if geo.point_in_polygon(hx, hy, [poly[0]]):
                poly.append(hole)
                break
    return polygons


# --------------------------------------------------------------------------- #
# Wildfire perimeters (yearly SHP files)
# --------------------------------------------------------------------------- #
def build_fire_perimeters(tolerance_m: float) -> dict:
    import shapefile  # pyshp: only this script needs it

    html = HTTP.get(FIRES_PAGE).text
    zips = sorted(set(re.findall(r'href="(http[^"]+/incendis(\d\d)\.zip)"', html)),
                  key=lambda z: (int(z[1]) < 50, z[1]))
    if not zips:
        raise RuntimeError("the wildfire ZIP files were not found on the Department's page")
    print(f"Wildfire perimeters · {len(zips)} yearly files")

    fires: dict[str, dict] = {}
    vertices_in = vertices_out = polygons_in = 0
    for url, yy in zips:
        year = 1900 + int(yy) if int(yy) >= 50 else 2000 + int(yy)
        zpath = RAW / f"incendis{yy}.zip"
        if not zpath.exists():
            zpath.write_bytes(HTTP.get(url).content)
            time.sleep(0.3)
        folder = RAW / f"incendis{yy}"
        with zipfile.ZipFile(zpath) as z:
            z.extractall(folder)
        shp = next(folder.rglob("*.shp"))
        prj = next(folder.rglob("*.prj"), None)
        if prj and "UTM_Zone_31N" not in prj.read_text(errors="ignore"):
            raise RuntimeError(f"{shp.name}: unexpected reference system; check before mixing")
        reader = shapefile.Reader(str(shp), encoding="latin-1")
        names = [f[0].upper() for f in reader.fields[1:]]

        for index, sr in enumerate(reader.iterShapeRecords()):
            rec = dict(zip(names, sr.record))
            shape = sr.shape
            polygons_in += 1
            parts = list(shape.parts) + [len(shape.points)]
            rings = [[(p[0], p[1]) for p in shape.points[parts[i]:parts[i + 1]]]
                     for i in range(len(parts) - 1)]
            vertices_in += sum(len(r) for r in rings)
            code = str(rec.get("CODI_FINAL") or f"{year}-{index}")
            fire = fires.setdefault(code, {
                "code": code, "year": year, "date": parse_fire_date(rec.get("DATA_INCEN"), year),
                "municipality": tidy_place(rec.get("MUNICIPI")),
                "polygons": [], "area_m2": 0.0,
            })
            for poly in group_rings(rings):
                fire["area_m2"] += geo.polygon_area(poly)
                simplified = [geo.simplify(r, tolerance_m) for r in poly]
                vertices_out += sum(len(r) for r in simplified)
                fire["polygons"].append([[[round(x), round(y)] for x, y in r] for r in simplified])

        print(f"   {year}: {len(reader):>4} polygons")

    out = []
    for fire in fires.values():
        if not fire["polygons"]:
            continue
        polys = [[[(x, y) for x, y in r] for r in p] for p in fire["polygons"]]
        out.append({**fire, "area_ha": round(fire.pop("area_m2") / 10000, 2),
                    "bbox": [round(v) for v in geo.bbox_of(polys)]})
    out.sort(key=lambda f: (f["year"], f["date"] or ""))
    path = write_gz("fire_perimeters.json.gz", out)
    years = sorted({f["year"] for f in out})
    print(f"   {polygons_in} polygons grouped into {len(out)} fires "
          f"({years[0]}-{years[-1]}) · vertices {vertices_in} -> {vertices_out} "
          f"(Douglas-Peucker {tolerance_m:.0f} m) · {path.stat().st_size / 1e6:.1f} MB")
    return {"fires": len(out), "polygons": polygons_in, "period": f"{years[0]}-{years[-1]}",
            "simplification_m": tolerance_m}


_PARTICLES = {"de", "del", "dels", "la", "les", "el", "els", "i", "a", "d", "l", "y"}


def tidy_place(name: str | None) -> str | None:
    """"OLESA DE MONTSERRAT" -> "Olesa de Montserrat"; "L'ESPLUGA" -> "L'Espluga".

    The SHP files of different years mix upper and lower case. Only what comes
    entirely in capitals is touched; what is already well formed ("Collbató")
    is left alone.
    """
    if not name:
        return None
    name = name.strip()
    if name != name.upper():
        return name
    words = []
    for i, word in enumerate(name.lower().split()):
        parts = re.split(r"(['’])", word)  # d'aro -> d ' aro
        out = []
        for part in parts:
            if part in ("'", "’") or not part:
                out.append(part)
            elif i > 0 and part in _PARTICLES:
                out.append(part)
            else:
                out.append(part[:1].upper() + part[1:])
        words.append("".join(out))
    return " ".join(words)


def parse_fire_date(value, year: int) -> str | None:
    """`DATA_INCEN` comes as dd/mm/yy text or as a date, depending on the year.

    The two-digit year is resolved with the file's year: that way 1999 and 2099
    are not confused.
    """
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m-%d")
    if not value:
        return None
    m = re.match(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", str(value))
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Wildfire statistics by municipality (Socrata)
# --------------------------------------------------------------------------- #
def build_fire_stats() -> dict:
    print("Wildfire statistics by municipality · Socrata")
    # The three datasets cover disjoint years (2011-2024, previous year, current
    # year). If they ever overlap, the first one to provide each year wins.
    # There is NO deduplication by content: the source has rows identical in every field
    # (same day, municipality and area) that are different fires, typically tiny fires
    # in a series.
    years_taken: set[int] = set()
    by_muni, per_dataset = defaultdict(list), {}
    for dataset, label in SOCRATA_FIRES.items():
        rows, offset = [], 0
        while True:
            page = HTTP.get(SOCRATA.format(id=dataset),
                            params={"$limit": 50000, "$offset": offset, "$order": ":id"}).json()
            if isinstance(page, dict) and page.get("error"):
                raise RuntimeError(f"Socrata {dataset}: {page}")
            rows.extend(page)
            if len(page) < 50000:
                break
            offset += len(page)
        years_here = {int(r["data_incendi"][:4]) for r in rows if r.get("data_incendi")}
        new_years = years_here - years_taken
        added = skipped = 0
        for r in rows:
            code = norm_muni(r.get("codi_municipi"))
            date = (r.get("data_incendi") or "")[:10] or None
            if not code or not date or int(date[:4]) not in new_years:
                skipped += 1
                continue
            ha = {k: float(r.get(k) or 0) for k in ("haforestal", "haarbrades", "hanoarbrad", "hanoforest")}
            by_muni[code].append({"date": date, **ha})
            added += 1
        years_taken |= new_years
        per_dataset[dataset] = {"label": label, "rows": len(rows), "added": added,
                                "years": sorted(years_here)}
        print(f"   {dataset} ({label}): {len(rows)} rows, {added} added, "
              f"{skipped} dropped (year already covered or no municipality)")
    dates = sorted(d["date"] for v in by_muni.values() for d in v if d["date"])
    write_gz("fire_stats.json.gz", by_muni)
    return {"datasets": per_dataset, "fires": sum(len(v) for v in by_muni.values()),
            "period": f"{dates[0][:4]}-{dates[-1][:4]}" if dates else None}


# --------------------------------------------------------------------------- #
# Avalanches (ICGC, Base de Dades d'Allaus de Catalunya)
# --------------------------------------------------------------------------- #
def wfs_all(type_name: str, props: list[str], page: int = 2000) -> list[dict]:
    """Every feature of a layer, paginated, in EPSG:25831."""
    feats, start = [], 0
    while True:
        params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                  "typeNames": type_name, "outputFormat": "application/json",
                  "srsName": "EPSG:25831", "count": page, "startIndex": start,
                  "propertyName": ",".join(props)}
        data = HTTP.get(NIVO_WFS, params=params).json()
        batch = data.get("features", [])
        feats.extend(batch)
        if len(batch) < page:
            return feats
        start += page


def polygons_of(geometry: dict | None, tolerance_m: float) -> list:
    """GeoJSON Polygon/MultiPolygon -> [[ring, ...], ...] simplified, integer metres."""
    if not geometry:
        return []
    coords = geometry.get("coordinates") or []
    polys = [coords] if geometry.get("type") == "Polygon" else coords
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            pts = geo.simplify([(float(p[0]), float(p[1])) for p in ring], tolerance_m)
            if len(pts) >= 4:
                rings.append([[round(x), round(y)] for x, y in pts])
        if rings:
            out.append(rings)
    return out


def observation_year(code: str | None) -> int | None:
    """"VFR123202303" -> 2023: zone code (3 letters + 3 digits), year, sequence.

    Almost every code has 12 characters with the year inside; the few that do not
    follow the pattern stay without a year.
    """
    if code and len(code) == 12 and code[6:10].isdigit():
        year = int(code[6:10])
        return year if 1900 <= year <= dt.date.today().year else None
    return None


def build_avalanches(tolerance_m: float) -> dict:
    print("ICGC · avalanche zones, observations, surveys and snow-climate zones (WFS)")
    zones, observations, surveys = [], [], []
    # Only coded features of types 1 and 2 are avalanche zones: the service also carries
    # an uncoded "type 3" polygon of 2,739 km2 (the study-area mask) and an uncoded
    # observation of 1,098 km2, which would put half the Pyrenees "inside a zone".
    for f in wfs_all("nivoallaus:zonesallaus", ["codizallau", "tipufoto", "the_geom"]):
        p = f.get("properties") or {}
        if not p.get("codizallau") or int(p.get("tipufoto") or 0) not in (1, 2):
            continue
        polys = polygons_of(f.get("geometry"), tolerance_m)
        if polys:
            zones.append({"code": p.get("codizallau"), "type": int(p.get("tipufoto") or 0),
                          "polygons": polys, "bbox": [round(v) for v in geo.bbox_of(polys)]})
    print(f"   {len(zones)} avalanche zones")
    for f in wfs_all("nivoallaus:observacions", ["codiallau", "geom"]):
        code = (f.get("properties") or {}).get("codiallau")
        if not code:
            continue
        polys = polygons_of(f.get("geometry"), tolerance_m)
        if polys:
            observations.append({"code": code, "year": observation_year(code), "polygons": polys,
                                 "bbox": [round(v) for v in geo.bbox_of(polys)]})
    years = sorted(o["year"] for o in observations if o["year"])
    print(f"   {len(observations)} observed avalanches ({years[0]}-{years[-1]})")
    for f in wfs_all("nivoallaus:enquestes", ["codi", "the_geom"]):
        polys = polygons_of(f.get("geometry"), tolerance_m)
        if polys:
            surveys.append({"code": (f.get("properties") or {}).get("codi"), "polygons": polys,
                            "bbox": [round(v) for v in geo.bbox_of(polys)]})
    print(f"   {len(surveys)} historical avalanches from surveys")
    nivo = []
    for f in wfs_all("nivoallaus:zonesnivoclima", ["ZONA", "the_geom"]):
        polys = polygons_of(f.get("geometry"), 100)
        if polys:
            nivo.append({"name": (f.get("properties") or {}).get("ZONA"), "polygons": polys,
                         "bbox": [round(v) for v in geo.bbox_of(polys)]})
    print(f"   {len(nivo)} snow-climate zones")
    path = write_gz("avalanches.json.gz", {"zones": zones, "observations": observations,
                                            "surveys": surveys, "nivo_zones": nivo})
    print(f"   -> {path.name} ({path.stat().st_size / 1e6:.1f} MB, simplified to {tolerance_m:.0f} m)")
    return {"zones": len(zones), "observations": len(observations), "surveys": len(surveys),
            "nivo_zones": len(nivo), "observations_period": f"{years[0]}-{years[-1]}",
            "simplification_m": tolerance_m}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=["agora", "fires", "stats", "avalanches"])
    p.add_argument("--tolerance", type=float, default=10.0,
                   help="perimeter simplification tolerance, in metres")
    args = p.parse_args()

    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    steps = {
        "agora": lambda: build_agora(),
        "fires": lambda: build_fire_perimeters(args.tolerance),
        "stats": lambda: build_fire_stats(),
        "avalanches": lambda: build_avalanches(args.tolerance),
    }
    for name, fn in steps.items():
        if args.only and args.only != name:
            continue
        started = time.time()
        try:
            manifest[name] = {**fn(), "downloaded_at": now}
        except Exception as exc:  # noqa: BLE001 - one broken block does not bring the others down
            print(f"   [failed] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        print(f"   ({time.time() - started:.0f}s)\n")

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest: {manifest_path}")
    for f in sorted(OUT.glob("*.json*")):
        print(f"   {f.name:<26} {f.stat().st_size / 1e6:6.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
