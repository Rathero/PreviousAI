"""The checks for `station-witness`. Each one returns a verdict with its evidence.

What Devin's code produces is only ever run in a subprocess on its own checkout
(`autonomy/drivers/`); what it is compared against comes from this process: the portal's
server-side aggregates (`oracle.py`), the product's own ERA5 series and reports built
from the base code.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ... import probe
from ...verdict import Check
from . import oracle

POINTS = [
    {"name": "El Masnou", "query": "El Masnou", "lat": 41.47978, "lon": 2.3188, "elevation_m": 14.0},
    {"name": "Vielha", "query": "Vielha", "lat": 42.70196, "lon": 0.79556, "elevation_m": 975.0},
]
# No XEMA station within 15 km: the witness must be None.
FAR = {"name": "Zaragoza", "lat": 41.6488, "lon": -0.8891, "elevation_m": 200.0}
DEAD_URL = "http://127.0.0.1:9"
SPOT_DATES = 12
COUNT_KEYS = ["hot_days_32", "hot_days_35", "hot_days_40", "tropical_nights"]
COMPARED = ["hot_days_35", "hot_days_32", "hot_days_40", "tropical_nights", "heat_record"]

ALLOWED = {
    "backend/app/providers/meteocat.py": "new",
    "backend/app/report.py": "any",
    "backend/app/indicators.py": "additions",
    "backend/app/config.py": "additions",
    "docs/station-witness.md": "new",
}

# Catalan and Spanish words a translated label must not keep (station names excepted).
NOT_ENGLISH = [
    "temperatura", "màxima", "maxima", "máxima", "mínima", "minima", "mitjana", "diària",
    "diaria", "representatiu", "estació", "estacio", "estacions", "estación", "precipitació",
    "dades", "datos", "meteorològiques", "meteorologiques", "lectura", "xarxa", "nits",
    "dies", "días", "noches", "anys", "años", "tropicals", "tropicales", "calor", "valor",
    "codi", "tancada", "operativa",
]
_NOT_ENGLISH = re.compile(r"\b(" + "|".join(map(re.escape, NOT_ENGLISH)) + r")\b", re.I)


class Context:
    """Lazily computed evidence shared by the checks of one gate run."""

    def __init__(self, target: Path, base: str | None, self_check: bool, seed: int, log,
                 main_backend: Path, base_tree: Path | None = None):
        self.target = target
        self.base_tree = base_tree
        self.base = base
        self.self_check = self_check
        self.seed = seed
        self.log = log
        self.main_backend = main_backend
        self.portal = oracle.Portal()
        self._memo: dict = {}

    def memo(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    # --- the reference ------------------------------------------------------------
    def expected(self, point: dict) -> dict:
        return self.memo(("expected", point["name"]), lambda: oracle.expected(
            self.portal, point["lat"], point["lon"], point["elevation_m"]))

    # --- Devin's code, run in its own checkout -------------------------------------
    def witnesses(self) -> dict:
        def run():
            self.log("running the witness on Devin's checkout (El Masnou, Vielha, Zaragoza)")
            return probe.run_driver(self.target, "witness.py",
                                    {"points": POINTS + [FAR], "mode": "live"}, timeout=900)
        return self.memo("witnesses", run)

    def witness(self, point: dict) -> dict:
        return (self.witnesses().get("results") or {}).get(point["name"]) or {}

    def cache_available(self) -> bool:
        from app import config  # the base tree's data dir: the local data cache
        archive = config.CACHE_DIR / "archive"
        return archive.exists() and any(archive.iterdir())

    def reports(self, which: str, env: dict | None = None, points=POINTS) -> dict:
        """which: "target" (Devin's code) or "base" (the product's code)."""
        tree = self.target if which == "target" else (self.base_tree or self.main_backend.parent)
        key = ("reports", which, tuple(sorted((env or {}).items())), tuple(p["name"] for p in points))

        def run():
            self.log(f"building reports with the {which} code: "
                     + ", ".join(p["query"] for p in points))
            return probe.run_driver(tree, "report.py", {"queries": [p["query"] for p in points]},
                                    env=env, timeout=1200)
        return self.memo(key, run)

    # --- the product's ERA5 series -------------------------------------------------------------
    def era5(self, point: dict):
        def run():
            from app import report as R
            from app import series as S
            from app.providers import geocoding, open_meteo, terrain

            async def go():
                place = await geocoding.resolve(point["query"])
                lat, lon = float(place["latitude"]), float(place["longitude"])
                relief = await terrain.profile(lat, lon)
                height = (relief or {}).get("center_m") or place.get("elevation")
                archive = await open_meteo.fetch_archive(lat, lon, height)
                return R._add_derived(S.DailySeries.from_open_meteo(archive))
            return asyncio.run(go())
        return self.memo(("era5", point["name"]), run)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fmt(v) -> str:
    return "None" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))


def _witness_or_error(ctx: Context, point: dict) -> tuple[dict | None, str | None]:
    res = ctx.witness(point)
    if not res:
        err = ctx.witnesses().get("error") or "the driver returned nothing"
        return None, f"{point['name']}: {err}"
    if res.get("error"):
        return None, f"{point['name']}: raised {res['error']}"
    value = res.get("value")
    if value is None:
        exp = ctx.expected(point)
        if exp.get("stations"):
            names = {s["code"]: s["name"] for s in exp.get("station_rows") or []}
            return None, (f"{point['name']}: returned None, but the rules call for "
                          f"{'→'.join(f'{c} ({names.get(c, c)})' for c in exp['stations'])}, "
                          f"{exp['period']}")
    if not isinstance(value, dict):
        return None, f"{point['name']}: returned {type(value).__name__}, expected a dict"
    return value, None


def _by_year(rows) -> dict[int, dict]:
    return {int(r.get("year")): r for r in (rows or []) if isinstance(r, dict) and "year" in r}


def _git(target: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True,
                          check=True, encoding="utf-8").stdout


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #
def scope(ctx: Context) -> Check:
    base = ctx.base or "origin/main"
    changed: dict[str, tuple[int, int]] = {}
    for line in _git(ctx.target, "diff", "--numstat", "--no-renames", f"{base}...HEAD").splitlines():
        a, d, path = line.split("\t", 2)
        changed[path] = (int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0)
    if ctx.self_check:  # uncommitted work on Devin's machine counts too
        for line in _git(ctx.target, "diff", "--numstat", "--no-renames", "HEAD").splitlines():
            a, d, path = line.split("\t", 2)
            changed[path] = (int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0)
        for path in _git(ctx.target, "ls-files", "--others", "--exclude-standard").splitlines():
            changed.setdefault(path, (1, 0))
    problems = []
    for path, (_, deleted) in sorted(changed.items()):
        rule = ALLOWED.get(path)
        if rule is None:
            problems.append(f"{path} is outside the task's scope")
        elif rule == "additions" and deleted:
            problems.append(f"{path}: {deleted} line(s) removed or changed (additions only)")
    if not (ctx.target / "backend/app/providers/meteocat.py").exists():
        problems.append("backend/app/providers/meteocat.py does not exist")
    return Check("scope", "Only the files the task allows were touched", not problems,
                 "; ".join(problems) or f"{len(changed)} file(s) changed, all within scope: "
                 + ", ".join(sorted(changed)), rule="Engineering rules: touch only")


def contract(ctx: Context) -> Check:
    out = ctx.witnesses()
    problems = []
    if out.get("error"):
        return Check("contract", "station_witness() exists and returns the agreed shape", False,
                     out["error"], rule="What to build")
    if not out.get("is_coroutine"):
        problems.append("station_witness is not an async function")
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        if w.get("available") is not True:
            problems.append(f"{p['name']}: 'available' is {w.get('available')!r}")
        for k, t in (("stations", list), ("period", str), ("years", list), ("observed", dict),
                     ("daily", dict), ("provenance", dict), ("limitation", str)):
            if not isinstance(w.get(k), t):
                problems.append(f"{p['name']}: '{k}' missing or not a {t.__name__}")
        if "splice" not in w:
            problems.append(f"{p['name']}: 'splice' missing (null when there is none)")
        d = w.get("daily") if isinstance(w.get("daily"), dict) else {}
        lens = {k: len(d.get(k) or []) for k in ("dates", "tmax", "tmin")}
        if len(set(lens.values())) != 1:
            problems.append(f"{p['name']}: daily lists differ in length {lens}")
        for s in w.get("stations") or []:
            miss = [k for k in ("code", "name", "latitude", "longitude", "elevation_m",
                                "distance_km", "operational", "used_from", "used_to") if k not in s]
            if miss:
                problems.append(f"{p['name']}: station {s.get('code')} lacks {miss}")
        miss = [k for k in COUNT_KEYS + ["heat_record"] if k not in (w.get("observed") or {})]
        if miss:
            problems.append(f"{p['name']}: observed lacks {miss}")
    far = ctx.witness(FAR)
    if far.get("error"):
        problems.append(f"{FAR['name']} (no station within 15 km): raised {far['error']}")
    elif far.get("value") is not None:
        problems.append(f"{FAR['name']} (no station within 15 km): expected None, got "
                        f"{type(far.get('value')).__name__}")
    return Check("contract", "station_witness() exists and returns the agreed shape",
                 not problems, "; ".join(problems) or "async, full shape for both towns, None "
                 "where no station qualifies", rule="Return value")


def station_choice(ctx: Context) -> Check:
    problems, ok = [], []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        exp = ctx.expected(p)
        want = exp["stations"]
        got = None if w is None else [s.get("code") for s in w.get("stations") or []]
        if err:
            problems.append(err)
        elif got != want:
            why = [r for r in exp["rejections"] if got and any(c in r for c in got)]
            names = {s["code"]: s["name"] for s in exp.get("station_rows") or []}
            problems.append(
                f"{p['name']}: you chose {'→'.join(got or []) or 'nothing'}; the rules call for "
                f"{'→'.join(f'{c} ({names.get(c, c)})' for c in want) if want else 'None'}"
                + (f". Why yours does not qualify: {' | '.join(why)}" if why else ""))
        else:
            ok.append(f"{p['name']} {'→'.join(got)}")
    return Check("station_choice", "The station (or splice) the rules call for", not problems,
                 "; ".join(problems) or "; ".join(ok), rule="R2, R4, R5, R6")


def period(ctx: Context) -> Check:
    problems, ok = [], []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        want = ctx.expected(p).get("period")
        if err:
            problems.append(err)
        elif w.get("period") != want:
            problems.append(f"{p['name']}: period {w.get('period')!r}, the rules give {want!r}")
        else:
            ok.append(f"{p['name']} {want}")
    return Check("period", "Longest run of complete years ending at the last complete year",
                 not problems, "; ".join(problems) or "; ".join(ok), rule="R3, R4")


def _year_diffs(ctx: Context, keys: list[str], tol: float = 0.0) -> list[str]:
    problems = []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        exp = _by_year(ctx.expected(p).get("years"))
        got = _by_year(w.get("years"))
        if sorted(got) != sorted(exp):
            problems.append(f"{p['name']}: years {min(got, default='-')}-{max(got, default='-')} "
                            f"({len(got)}), expected {min(exp)}-{max(exp)} ({len(exp)})")
        bad = []
        for y in sorted(exp):
            for k in keys:
                a, b = got.get(y, {}).get(k), exp[y].get(k)
                if a is None or b is None or abs(float(a) - float(b)) > tol:
                    bad.append(f"{y} {k}: yours {_fmt(a)}, source {_fmt(b)}")
        if bad:
            problems.append(f"{p['name']}: {len(bad)} mismatch(es), e.g. " + "; ".join(bad[:4]))
    return problems


def completeness(ctx: Context) -> Check:
    problems = _year_diffs(ctx, ["valid_tx_days", "valid_tn_days"])
    return Check("completeness", "Valid days per year match the portal's own count",
                 not problems, "; ".join(problems) or "every year matches the server-side count",
                 rule="R1, R3")


def counts(ctx: Context) -> Check:
    problems = list(dict.fromkeys(_year_diffs(ctx, COUNT_KEYS)
                                  + _year_diffs(ctx, ["tmax_max"], tol=0.05)))
    return Check("counts", "Hot days, tropical nights and yearly maxima match the portal",
                 not problems, "; ".join(problems) or "every year and metric matches",
                 rule="R1, R7")


def observed(ctx: Context) -> Check:
    problems, ok = [], []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        exp = ctx.expected(p).get("observed") or {}
        got = w.get("observed") or {}
        for k, v in exp.items():
            g = got.get(k)
            if not isinstance(g, (int, float)) or abs(g - v) > (0.05 if k == "heat_record" else 0.02):
                problems.append(f"{p['name']} {k}: yours {_fmt(g)}, expected {_fmt(v)}")
        ok.append(f"{p['name']} {got.get('tropical_nights')} tropical nights/yr, "
                  f"{got.get('hot_days_35')} days ≥35 °C")
    return Check("observed", "Observed rates over the period", not problems,
                 "; ".join(problems) or "; ".join(ok), rule="R7")


def splice(ctx: Context) -> Check:
    problems, ok = [], []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        exp = ctx.expected(p)
        want, got = exp.get("splice"), w.get("splice")
        if want is None:
            if got:
                problems.append(f"{p['name']}: reported a splice {got}, the rules call for none")
        elif not isinstance(got, dict):
            problems.append(f"{p['name']}: no splice reported; expected {want['from']}→{want['to']}")
        else:
            for k, tol in (("from", 0), ("to", 0), ("overlap_days", 1),
                           ("tmax_mean_diff", 0.05), ("tmin_mean_diff", 0.05)):
                a, b = got.get(k), want.get(k)
                if isinstance(b, str) and a != b or (not isinstance(b, str) and (
                        not isinstance(a, (int, float)) or abs(a - b) > tol)):
                    problems.append(f"{p['name']} splice {k}: yours {_fmt(a)}, expected {_fmt(b)}")
            if not problems:
                ok.append(f"{p['name']} {want['from']}→{want['to']}, {want['overlap_days']} days "
                          f"overlap, Tx {want['tmax_mean_diff']:+} °C, Tn {want['tmin_mean_diff']:+} °C")
        # used_from / used_to: the first and last daily dates each station supplies.
        if exp.get("parts") and isinstance(w.get("daily"), dict):
            dates = [dt.date.fromisoformat(d) for d in w["daily"].get("dates") or []]
            for s in w.get("stations") or []:
                mine = [d for d in dates if oracle.supplier(exp, d) == s.get("code")]
                if mine and (s.get("used_from") != mine[0].isoformat()
                             or s.get("used_to") != mine[-1].isoformat()):
                    problems.append(f"{p['name']} {s.get('code')}: used_from/used_to "
                                    f"{s.get('used_from')}/{s.get('used_to')}, its daily dates "
                                    f"run {mine[0]}/{mine[-1]}")
    return Check("splice", "Station splice and overlap statistics", not problems,
                 "; ".join(problems) or "; ".join(ok) or "no splice needed", rule="R5")


def spot_checks(ctx: Context) -> Check:
    rng = random.Random(ctx.seed)
    problems, n = [], 0
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        exp = ctx.expected(p)
        if err or not exp.get("period"):
            problems.append(err or f"{p['name']}: no expected period")
            continue
        y0, y1 = (int(x) for x in exp["period"].split("-"))
        start, end = dt.date(y0, 1, 1), dt.date(y1, 12, 31)
        picks = sorted({start + dt.timedelta(days=rng.randrange((end - start).days + 1))
                        for _ in range(SPOT_DATES)})
        daily = w.get("daily") or {}
        mine = {d: (tx, tn) for d, tx, tn in zip(daily.get("dates") or [], daily.get("tmax") or [],
                                                  daily.get("tmin") or [])}
        by_station: dict[str, list] = {}
        for d in picks:
            by_station.setdefault(oracle.supplier(exp, d), []).append(d)
        for code, days in by_station.items():
            raw = ctx.portal.readings_on(code, days)
            for d in days:
                n += 1
                src = raw.get(d, {"tx": None, "tn": None})
                got = mine.get(d.isoformat(), (None, None))
                for name, a, b in (("Tx", got[0], src["tx"]), ("Tn", got[1], src["tn"])):
                    if (a is None) != (b is None) or (a is not None and abs(float(a) - b) > 0.05):
                        problems.append(f"{p['name']} {d} ({code}) {name}: yours {_fmt(a)}, "
                                        f"source {_fmt(b)}")
    if problems and not n:
        detail = "; ".join(problems)
    elif problems:
        detail = f"{len(problems)} of {n * 2} readings differ, e.g. " + "; ".join(problems[:5])
    else:
        detail = f"{n} random days × 2 variables identical to the portal"
    return Check("spot_checks", f"Random days read back from the source (seed {ctx.seed})",
                 not problems, detail, rule="R1, R5, R8")


def physics(ctx: Context) -> Check:
    problems, ok = [], []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        d = w.get("daily") or {}
        dates, tx, tn = d.get("dates") or [], d.get("tmax") or [], d.get("tmin") or []
        if not dates:
            problems.append(f"{p['name']}: empty daily series")
            continue
        inverted = sum(1 for a, b in zip(tx, tn) if a is not None and b is not None and b > a)
        wild = sum(1 for v in tx + tn if v is not None and not -35 <= v <= 48)
        order = sum(1 for a, b in zip(dates, dates[1:]) if b <= a)
        if inverted:
            problems.append(f"{p['name']}: {inverted} day(s) with Tn above Tx")
        if wild:
            problems.append(f"{p['name']}: {wild} value(s) outside -35..48 °C (units?)")
        if order:
            problems.append(f"{p['name']}: dates not strictly ascending ({order} places)")
        per = w.get("period") or ""
        if per and "-" in per and dates:
            y0, y1 = (int(x) for x in per.split("-"))
            if dates[0][:4] < str(y0) or dates[-1][:4] > str(y1):
                problems.append(f"{p['name']}: daily runs {dates[0]}..{dates[-1]}, outside {per}")
        valid_tx = [v for v in tx if v is not None]
        mean_tx = sum(valid_tx) / len(valid_tx) if valid_tx else None
        if mean_tx is None or not 5 <= mean_tx <= 30:
            problems.append(f"{p['name']}: mean Tx {_fmt(mean_tx)} °C is not a climate on Earth "
                            f"at this place")
        # The thermometer and the model must tell the same day-to-day story.
        if ctx.cache_available():
            s = ctx.era5(p)
            model = dict(zip((x.isoformat() for x in s.dates), s.get("temperature_2m_max")))
            pairs = [(a, model[dd]) for dd, a in zip(dates, tx)
                     if a is not None and model.get(dd) is not None]
            r = _pearson(pairs)
            if r is None or r < 0.9:
                problems.append(f"{p['name']}: daily Tx correlates r={_fmt(r)} with ERA5 over "
                                f"{len(pairs)} days (needs ≥ 0.9: wrong station, dates or units)")
            else:
                ok.append(f"{p['name']} r={r:.3f} with ERA5 over {len(pairs)} days")
        else:
            ok.append(f"{p['name']} ERA5 correlation skipped (no local data cache here)")
    return Check("physics", "Physically possible, and in step with the model day to day",
                 not problems, "; ".join(problems) or "; ".join(ok), rule="R8")


def _pearson(pairs):
    if len(pairs) < 30:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(sxy / (sx * sy), 4) if sx and sy else None


def provenance(ctx: Context) -> Check:
    problems = []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        prov = w.get("provenance") or {}
        empty = [k for k in ("source", "dataset", "period", "resolution", "method", "confidence",
                             "url", "scale", "scale_kind") if not prov.get(k)]
        if empty:
            problems.append(f"{p['name']}: provenance lacks {empty}")
        if prov.get("confidence") not in ("high", "medium", "low"):
            problems.append(f"{p['name']}: confidence {prov.get('confidence')!r}")
        if prov.get("scale_kind") != "point":
            problems.append(f"{p['name']}: scale_kind {prov.get('scale_kind')!r}, expected 'point'")
        if prov.get("period") != w.get("period"):
            problems.append(f"{p['name']}: provenance period {prov.get('period')!r} ≠ "
                            f"{w.get('period')!r}")
        if not str(prov.get("url", "")).startswith("http"):
            problems.append(f"{p['name']}: provenance url is not a link")
        if len(w.get("limitation") or "") < 80:
            problems.append(f"{p['name']}: limitation shorter than 80 characters")
    return Check("provenance", "Every number says where it comes from and what it does not say",
                 not problems, "; ".join(problems) or "complete for both towns",
                 rule="Engineering rules: provenance")


def _strings(value, skip: set[str], path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("daily", "url", "code", "codes"):
                continue
            yield from _strings(v, skip, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, skip, f"{path}[{i}]")
    elif isinstance(value, str) and value not in skip:
        yield path, value


def english(ctx: Context) -> Check:
    problems = []
    for p in POINTS:
        w, err = _witness_or_error(ctx, p)
        if err:
            problems.append(err)
            continue
        names = {s.get("name") for s in w.get("stations") or []}
        for where, text in _strings(w, names):
            for name in names:
                text = text.replace(name or "\0", "")
            m = _NOT_ENGLISH.search(text)
            if m:
                problems.append(f"{p['name']} {where}: '{m.group(0)}' in {text[:90]!r}")
    return Check("english", "English in every string a person reads (station names excepted)",
                 not problems, "; ".join(problems[:6]) or "no Catalan or Spanish left",
                 rule="Engineering rules: English")


def cache(ctx: Context) -> Check:
    with tempfile.TemporaryDirectory(prefix="pai-gate-cache-") as tmp:
        out = probe.run_driver(ctx.target, "witness.py",
                               {"points": [POINTS[1]], "mode": "cache", "dead_url": DEAD_URL},
                               env={"DATA_DIR": tmp}, timeout=600)
    r = (out.get("results") or {}).get(POINTS[1]["name"]) or {}
    if out.get("error") or r.get("error"):
        return Check("cache", "A repeated call works with the portal down", False,
                     out.get("error") or r.get("error"), rule="Engineering rules: cache")
    same = r.get("first") == r.get("second") and r.get("first") is not None
    return Check("cache", "A repeated call works with the portal down", same,
                 "second call (portal unreachable, METEOCAT_URL redirected at call time) returned "
                 "the same witness" if same else
                 "after one live call, the same call with the portal unreachable returned "
                 f"{str(r.get('second'))[:120]!r}: cache for ≥ 7 days and read "
                 "config.METEOCAT_URL at call time", rule="Engineering rules: cache")


def degradation(ctx: Context) -> Check:
    problems, ok = [], []
    with tempfile.TemporaryDirectory(prefix="pai-gate-dead-") as tmp:
        out = probe.run_driver(ctx.target, "witness.py", {"points": [POINTS[1]], "mode": "live"},
                               env={"DATA_DIR": tmp, "METEOCAT_URL": DEAD_URL}, timeout=300)
    r = (out.get("results") or {}).get(POINTS[1]["name"]) or {}
    if out.get("error") or r.get("error"):
        problems.append(f"portal down, empty cache: raised {out.get('error') or r.get('error')}")
    elif r.get("value") is not None and not (isinstance(r["value"], dict)
                                             and r["value"].get("available") is False
                                             and isinstance(r["value"].get("note"), str)):
        problems.append(f"portal down, empty cache: returned {str(r.get('value'))[:100]!r}; "
                        "expected None or {'available': false, 'note': ...}")
    elif r.get("seconds", 0) > 90:
        problems.append(f"portal down: took {r['seconds']:.0f} s to give up")
    else:
        ok.append(f"direct call gave up cleanly in {r.get('seconds', 0):.1f} s")
    if ctx.cache_available() and not ctx.self_check:
        # The whole report with the portal down and no cached answer: move the product's
        # meteocat cache aside for the duration.
        from app import config
        folder = config.CACHE_DIR / "meteocat"
        aside = config.CACHE_DIR / "_meteocat_gate_aside"
        moved = folder.exists()
        if moved:
            shutil.rmtree(aside, ignore_errors=True)
            folder.rename(aside)
        try:
            rep = ctx.reports("target", env={"METEOCAT_URL": DEAD_URL}, points=[POINTS[1]])
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            if moved:
                aside.rename(folder)
        v = (rep.get("results") or {}).get(POINTS[1]["query"]) or {}
        if rep.get("error") or v.get("error"):
            problems.append(f"Vielha report with the portal down did not build: "
                            f"{rep.get('error') or v.get('error')}")
        else:
            wit = v.get("witness")
            warned = any("meteocat" in (x or "").lower() or "station" in (x or "").lower()
                         for x in v.get("warnings") or [])
            if not (isinstance(wit, dict) and wit.get("available") is False and wit.get("note")):
                problems.append(f"Vielha report with the portal down: witness {str(wit)[:100]!r}, "
                                "expected {'available': false, 'note': ...}")
            elif not warned:
                problems.append("Vielha report with the portal down: no line in warnings")
            else:
                ok.append("the Vielha report still builds and says the station check is unavailable")
    return Check("degradation", "With the portal down, the witness and the report degrade",
                 not problems, "; ".join(problems) or "; ".join(ok),
                 rule="Report wiring: when the portal fails")


def report(ctx: Context) -> Check:
    if not ctx.cache_available():
        return Check("report", "The report shows the witness beside the model, same years", None,
                     "skipped: needs the local data cache (the authoritative gate runs it)")
    from app import report as R
    rep = ctx.reports("target")
    problems, ok = [], []
    if rep.get("error"):
        return Check("report", "The report shows the witness beside the model, same years", False,
                     rep["error"], rule="Report wiring")
    for p in POINTS:
        v = (rep.get("results") or {}).get(p["query"]) or {}
        if v.get("error"):
            problems.append(f"{p['name']}: report failed: {v['error']}")
            continue
        wit = v.get("witness")
        if not isinstance(wit, dict) or wit.get("available") is not True:
            problems.append(f"{p['name']}: report['witness'] is {str(wit)[:80]!r}")
            continue
        if "daily" in wit:
            problems.append(f"{p['name']}: report['witness'] still carries 'daily'")
        per = wit.get("period")
        if wit.get("model_period") != per:
            problems.append(f"{p['name']}: model_period {wit.get('model_period')!r} ≠ period {per!r}")
        model = R._matched_window(ctx.era5(p), None, per)
        comps = {c.get("key"): c for c in wit.get("comparisons") or [] if isinstance(c, dict)}
        missing = [k for k in COMPARED if k not in comps]
        if missing:
            problems.append(f"{p['name']}: comparisons lack {missing}")
        for k in COMPARED:
            c = comps.get(k)
            if not c:
                continue
            m, o = model.get(k), (wit.get("observed") or {}).get(k)
            if m is None or not isinstance(c.get("model"), (int, float)) or abs(c["model"] - m) > 0.02:
                problems.append(f"{p['name']} {k}: model {_fmt(c.get('model'))}, ERA5 over "
                                f"{per} gives {_fmt(m and round(m, 2))}")
                continue
            if c.get("observed") != o:
                problems.append(f"{p['name']} {k}: observed {_fmt(c.get('observed'))} ≠ witness "
                                f"{_fmt(o)}")
            diff = round(c["model"] - (o or 0), 2)
            if not isinstance(c.get("difference"), (int, float)) or abs(c["difference"] - diff) > 0.011:
                problems.append(f"{p['name']} {k}: difference {_fmt(c.get('difference'))}, "
                                f"model − observed = {diff}")
            if o is not None:
                want = ("high" if abs(c["model"] - o) < 1e-9 else "low" if o == 0 else
                        "high" if abs(c["model"] - o) / abs(o) <= 0.15 else
                        "medium" if abs(c["model"] - o) / abs(o) <= 0.35 else "low")
                if c.get("agreement") != want:
                    problems.append(f"{p['name']} {k}: agreement {c.get('agreement')!r}, the rule "
                                    f"gives {want!r}")
        if not any(x.startswith(p["name"]) for x in problems):
            t = comps.get("tropical_nights", {})
            h = comps.get("hot_days_35", {})
            ok.append(f"{p['name']}: tropical nights model {t.get('model')} vs station "
                      f"{t.get('observed')}; days ≥35 °C model {h.get('model')} vs station "
                      f"{h.get('observed')} ({per})")
    return Check("report", "The report shows the witness beside the model, same years",
                 not problems, "; ".join(problems[:6]) or "; ".join(ok), rule="Report wiring")


def invariance(ctx: Context) -> Check:
    if ctx.self_check or not ctx.cache_available():
        return Check("invariance", "No score, level, card or order changed", None,
                     "skipped: runs against the base code on the authoritative gate")
    mine, base = ctx.reports("target"), ctx.reports("base")
    if mine.get("error") or base.get("error"):
        return Check("invariance", "No score, level, card or order changed", False,
                     mine.get("error") or f"base reports failed: {base.get('error')}")
    problems = []
    for p in POINTS:
        a = (mine.get("results") or {}).get(p["query"]) or {}
        b = (base.get("results") or {}).get(p["query"]) or {}
        if a.get("error"):
            problems.append(f"{p['name']}: {a['error']}")
            continue
        if a.get("hazards") != b.get("hazards"):
            problems.append(f"{p['name']}: cards now {a.get('hazards')}, before {b.get('hazards')}")
        if a.get("overall") != b.get("overall"):
            problems.append(f"{p['name']}: overall {a.get('overall')} vs {b.get('overall')}")
    return Check("invariance", "No score, level, card or order changed", not problems,
                 "; ".join(problems) or "El Masnou and Vielha: every card, score, level and the "
                 "order identical to the base code", rule="Report wiring: nothing else changes")


CHECKS = [scope, contract, station_choice, period, completeness, counts, observed, splice,
          spot_checks, physics, provenance, english, cache, degradation, report, invariance]
