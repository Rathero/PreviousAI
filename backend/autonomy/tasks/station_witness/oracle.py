"""Reference answers for the station-witness task, reached by a different road.

Devin's adapter downloads daily readings and counts them in Python. The gate asks
the open-data portal's own database instead (Socrata SoQL aggregates: count and max
grouped by year, with the thresholds applied server-side), so when both agree it is
evidence, not an echo of the same code. Only the overlap between two stations and
the spot checks read individual days.

Every rule here is written, in words, in SPEC.md: the gate never holds Devin to a
rule it was not told.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass, field

import httpx

DAILY = "7bvh-jvq2"      # Meteocat · XEMA daily data
STATIONS = "yqwd-vj5e"   # Meteocat · XEMA station metadata
TX, TN = "1001", "1002"  # daily maximum and minimum temperature
VALID = "Representatiu"
OPERATIONAL = "2"        # codi_estat_ema

RADIUS_KM = 15.0
MAX_HEIGHT_GAP_M = 150.0
SPLICE_KM = 1.0
SPLICE_HEIGHT_GAP_M = 60.0
SPLICE_MIN_OVERLAP_DAYS = 180
SPLICE_MAX_MEAN_DIFF_C = 1.0
MIN_VALID_DAYS = 330
MIN_YEARS = 10
MAX_YEARS = 30

# metric -> (variable, threshold)
COUNTS = {
    "hot_days_32": (TX, 32.0),
    "hot_days_35": (TX, 35.0),
    "hot_days_40": (TX, 40.0),
    "tropical_nights": (TN, 20.0),
}


def end_year(today: dt.date | None = None) -> int:
    """The last complete calendar year."""
    return (today or dt.date.today()).year - 1


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _iso(d: dt.date) -> str:
    return f"{d.isoformat()}T00:00:00.000"


class Portal:
    """Minimal SoQL client with retries and an in-process memo."""

    def __init__(self, base: str = "https://analisi.transparenciacatalunya.cat/resource"):
        self.base = base.rstrip("/")
        self._memo: dict = {}

    def get(self, dataset: str, params: dict) -> list[dict]:
        key = (dataset, tuple(sorted(params.items())))
        if key in self._memo:
            return self._memo[key]
        last = None
        for attempt in range(4):
            try:
                r = httpx.get(f"{self.base}/{dataset}.json", params=params, timeout=120)
                if r.status_code == 200:
                    self._memo[key] = r.json()
                    return self._memo[key]
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"open-data portal did not answer ({dataset}): {last}")

    # --- metadata ---------------------------------------------------------------
    def stations(self) -> list[dict]:
        out = []
        for s in self.get(STATIONS, {"$limit": 5000}):
            try:
                out.append({"code": s["codi_estacio"], "name": s.get("nom_estacio"),
                            "latitude": float(s["latitud"]), "longitude": float(s["longitud"]),
                            "elevation_m": float(s["altitud"]),
                            "operational": s.get("codi_estat_ema") == OPERATIONAL})
            except (KeyError, TypeError, ValueError):
                continue
        return out

    # --- server-side aggregates -----------------------------------------------------
    @staticmethod
    def _where(code: str, var: str, since: dt.date | None, before: dt.date | None,
               extra: str = "") -> str:
        w = f"codi_estacio='{code}' AND codi_variable='{var}' AND estat='{VALID}'"
        if since:
            w += f" AND data_lectura >= '{_iso(since)}'"
        if before:
            w += f" AND data_lectura < '{_iso(before)}'"
        return w + extra

    def per_year(self, code: str, var: str, *, since=None, before=None,
                 threshold: float | None = None) -> dict[int, int]:
        extra = f" AND valor::number >= {threshold}" if threshold is not None else ""
        rows = self.get(DAILY, {
            "$select": "date_extract_y(data_lectura) AS y, count(*) AS n",
            "$where": self._where(code, var, since, before, extra),
            "$group": "y", "$limit": 1000})
        return {int(r["y"]): int(r["n"]) for r in rows if r.get("y") is not None}

    def max_per_year(self, code: str, var: str, *, since=None, before=None) -> dict[int, float]:
        rows = self.get(DAILY, {
            "$select": "date_extract_y(data_lectura) AS y, max(valor::number) AS m",
            "$where": self._where(code, var, since, before),
            "$group": "y", "$limit": 1000})
        return {int(r["y"]): float(r["m"]) for r in rows if r.get("m") is not None}

    def first_valid_day(self, code: str) -> dt.date | None:
        rows = self.get(DAILY, {
            "$select": "min(data_lectura) AS d",
            "$where": f"codi_estacio='{code}' AND codi_variable in ('{TX}','{TN}') "
                      f"AND estat='{VALID}'"})
        d = rows[0].get("d") if rows else None
        return dt.date.fromisoformat(d[:10]) if d else None

    def last_valid_day(self, code: str) -> dt.date | None:
        rows = self.get(DAILY, {
            "$select": "max(data_lectura) AS d",
            "$where": f"codi_estacio='{code}' AND codi_variable in ('{TX}','{TN}') "
                      f"AND estat='{VALID}'"})
        d = rows[0].get("d") if rows else None
        return dt.date.fromisoformat(d[:10]) if d else None

    # --- individual days ----------------------------------------------------------------
    def days(self, code: str, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
        """{date: {"tx": float | None, "tn": float | None}}, valid readings only."""
        rows = self.get(DAILY, {
            "$select": "data_lectura, codi_variable, valor",
            "$where": f"codi_estacio='{code}' AND codi_variable in ('{TX}','{TN}') "
                      f"AND estat='{VALID}' AND data_lectura >= '{_iso(start)}' "
                      f"AND data_lectura <= '{_iso(end)}'",
            "$order": "data_lectura", "$limit": 50000})
        out: dict[dt.date, dict] = {}
        for r in rows:
            d = dt.date.fromisoformat(r["data_lectura"][:10])
            slot = out.setdefault(d, {"tx": None, "tn": None})
            slot["tx" if r["codi_variable"] == TX else "tn"] = float(r["valor"])
        return out

    def readings_on(self, code: str, dates: list[dt.date]) -> dict[dt.date, dict]:
        if not dates:
            return {}
        listed = ",".join(f"'{_iso(d)}'" for d in dates)
        rows = self.get(DAILY, {
            "$select": "data_lectura, codi_variable, valor",
            "$where": f"codi_estacio='{code}' AND codi_variable in ('{TX}','{TN}') "
                      f"AND estat='{VALID}' AND data_lectura in ({listed})",
            "$limit": 5000})
        out = {d: {"tx": None, "tn": None} for d in dates}
        for r in rows:
            d = dt.date.fromisoformat(r["data_lectura"][:10])
            out.setdefault(d, {"tx": None, "tn": None})[
                "tx" if r["codi_variable"] == TX else "tn"] = float(r["valor"])
        return out


# --------------------------------------------------------------------------- #
# The expected answer
# --------------------------------------------------------------------------- #
@dataclass
class Part:
    code: str
    since: dt.date | None = None   # first day this station supplies (inclusive)
    before: dt.date | None = None  # first day it no longer supplies (exclusive)


@dataclass
class Option:
    parts: list[Part]
    stations: list[dict]
    splice: dict | None = None
    valid_tx: dict[int, int] = field(default_factory=dict)
    valid_tn: dict[int, int] = field(default_factory=dict)
    period: tuple[int, int] | None = None
    rejected: str | None = None

    @property
    def distance_km(self) -> float:
        return self.stations[-1]["distance_km"]

    @property
    def years(self) -> int:
        return 0 if not self.period else self.period[1] - self.period[0] + 1


def _sum_parts(portal: Portal, parts: list[Part], fn) -> dict[int, float]:
    total: dict[int, float] = {}
    for p in parts:
        for y, n in fn(p).items():
            total[y] = total.get(y, 0) + n
    return total


def _period(valid_tx: dict, valid_tn: dict, end: int) -> tuple[int, int] | None:
    years = []
    y = end
    while (len(years) < MAX_YEARS and valid_tx.get(y, 0) >= MIN_VALID_DAYS
           and valid_tn.get(y, 0) >= MIN_VALID_DAYS):
        years.append(y)
        y -= 1
    return (min(years), max(years)) if years else None


def overlap(portal: Portal, old: str, new: str) -> dict | None:
    a0, a1 = portal.first_valid_day(old), portal.last_valid_day(old)
    b0, b1 = portal.first_valid_day(new), portal.last_valid_day(new)
    if not (a0 and a1 and b0 and b1):
        return None
    start, end = max(a0, b0), min(a1, b1)
    if start > end:
        return {"from": old, "to": new, "overlap_days": 0, "tmax_mean_diff": None,
                "tmin_mean_diff": None, "successor_start": b0.isoformat()}
    da, db = portal.days(old, start, end), portal.days(new, start, end)
    both = [d for d in da if d in db and None not in (da[d]["tx"], da[d]["tn"],
                                                     db[d]["tx"], db[d]["tn"])]
    mean = (lambda xs: round(sum(xs) / len(xs), 2)) if both else (lambda xs: None)
    return {"from": old, "to": new, "overlap_days": len(both),
            "tmax_mean_diff": mean([db[d]["tx"] - da[d]["tx"] for d in both]),
            "tmin_mean_diff": mean([db[d]["tn"] - da[d]["tn"] for d in both]),
            "successor_start": b0.isoformat()}


def options(portal: Portal, lat: float, lon: float, elevation_m: float,
            end: int) -> list[Option]:
    everything = portal.stations()
    for s in everything:
        s["distance_km"] = round(km(lat, lon, s["latitude"], s["longitude"]), 2)
    near = [s for s in everything if s["distance_km"] <= RADIUS_KM]
    out: list[Option] = []
    for s in near:
        if abs(s["elevation_m"] - elevation_m) > MAX_HEIGHT_GAP_M:
            out.append(Option([Part(s["code"])], [s], rejected=(
                f"{s['code']} {s['name']} is {s['elevation_m'] - elevation_m:+.0f} m from the "
                f"point's height (rule 2: at most {MAX_HEIGHT_GAP_M:.0f} m)")))
            continue
        out.append(Option([Part(s["code"])], [s]))
        if s["operational"]:
            continue
        # Rule 5: a closed station can be continued by its operational successor.
        for b in everything:
            if (b["operational"] and b["code"] != s["code"]
                    and km(s["latitude"], s["longitude"], b["latitude"], b["longitude"]) <= SPLICE_KM
                    and abs(b["elevation_m"] - s["elevation_m"]) <= SPLICE_HEIGHT_GAP_M
                    and b["distance_km"] <= RADIUS_KM
                    and abs(b["elevation_m"] - elevation_m) <= MAX_HEIGHT_GAP_M):
                ov = overlap(portal, s["code"], b["code"])
                if not ov:
                    continue
                opt = Option([Part(s["code"], before=dt.date.fromisoformat(ov["successor_start"])),
                              Part(b["code"], since=dt.date.fromisoformat(ov["successor_start"]))],
                             [s, b], splice={k: v for k, v in ov.items() if k != "successor_start"})
                if ov["overlap_days"] < SPLICE_MIN_OVERLAP_DAYS:
                    opt.rejected = (f"splice {s['code']}→{b['code']}: only {ov['overlap_days']} "
                                    f"overlapping days (rule 5: at least {SPLICE_MIN_OVERLAP_DAYS})")
                elif (abs(ov["tmax_mean_diff"]) > SPLICE_MAX_MEAN_DIFF_C
                      or abs(ov["tmin_mean_diff"]) > SPLICE_MAX_MEAN_DIFF_C):
                    opt.rejected = (f"splice {s['code']}→{b['code']}: the stations disagree by "
                                    f"{ov['tmax_mean_diff']} / {ov['tmin_mean_diff']} °C "
                                    f"(rule 5: within ±{SPLICE_MAX_MEAN_DIFF_C})")
                out.append(opt)
    for opt in out:
        if opt.rejected:
            continue
        opt.valid_tx = _sum_parts(portal, opt.parts, lambda p: portal.per_year(
            p.code, TX, since=p.since, before=p.before))
        opt.valid_tn = _sum_parts(portal, opt.parts, lambda p: portal.per_year(
            p.code, TN, since=p.since, before=p.before))
        opt.period = _period(opt.valid_tx, opt.valid_tn, end)
        codes = "→".join(p.code for p in opt.parts)
        if not opt.period:
            opt.rejected = (f"{codes}: {end} is not a complete year (rule 3/4: the record must "
                            f"reach the last complete year with ≥{MIN_VALID_DAYS} valid days of "
                            f"both Tx and Tn)")
        elif opt.years < MIN_YEARS:
            opt.rejected = (f"{codes}: only {opt.years} complete consecutive years "
                            f"({opt.period[0]}-{opt.period[1]}; rule 4: at least {MIN_YEARS})")
    return out


def expected(portal: Portal, lat: float, lon: float, elevation_m: float,
             end: int | None = None) -> dict:
    """The witness the rules call for, or {"station": None} with every rejection."""
    end = end or end_year()
    opts = options(portal, lat, lon, elevation_m, end)
    good = sorted((o for o in opts if not o.rejected), key=lambda o: (o.distance_km, -o.years))
    rejections = [o.rejected for o in opts if o.rejected]
    if not good:
        return {"stations": None, "rejections": rejections}
    best = good[0]
    y0, y1 = best.period
    years = []
    counts = {k: _sum_parts(portal, best.parts, lambda p, v=v, t=t: portal.per_year(
        p.code, v, since=p.since, before=p.before, threshold=t)) for k, (v, t) in COUNTS.items()}
    tmax = {}
    for p in best.parts:
        for y, m in portal.max_per_year(p.code, TX, since=p.since, before=p.before).items():
            tmax[y] = max(m, tmax.get(y, -99.0))
    for y in range(y0, y1 + 1):
        years.append({"year": y, "valid_tx_days": best.valid_tx.get(y, 0),
                      "valid_tn_days": best.valid_tn.get(y, 0),
                      **{k: int(counts[k].get(y, 0)) for k in COUNTS},
                      "tmax_max": tmax.get(y)})
    tx_days = sum(r["valid_tx_days"] for r in years)
    tn_days = sum(r["valid_tn_days"] for r in years)
    observed = {k: round(sum(r[k] for r in years) / (tx_days if COUNTS[k][0] == TX else tn_days)
                         * 365.25, 2) for k in COUNTS}
    observed["heat_record"] = max(r["tmax_max"] for r in years if r["tmax_max"] is not None)
    return {
        "stations": [s["code"] for s in best.stations],
        "station_rows": best.stations,
        "parts": [{"code": p.code, "since": p.since and p.since.isoformat(),
                   "before": p.before and p.before.isoformat()} for p in best.parts],
        "splice": best.splice,
        "period": f"{y0}-{y1}",
        "years": years,
        "observed": observed,
        "rejections": rejections,
    }


def supplier(exp: dict, day: dt.date) -> str:
    """Which station the spliced series takes a given day from."""
    for p in exp["parts"]:
        if p["since"] and day < dt.date.fromisoformat(p["since"]):
            continue
        if p["before"] and day >= dt.date.fromisoformat(p["before"]):
            continue
        return p["code"]
    return exp["parts"][-1]["code"]
