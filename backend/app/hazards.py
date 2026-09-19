"""Climate hazards: ERA5 daily series -> traceable indicators + score.

Three hazards come from the climate record: extreme heat, extreme rain (the driver of
flash and surface-water flooding) and fire weather. Each `hazard_*` function returns a
Hazard with:
  - a primary metric, the one that feeds the score;
  - supporting indicators, all with their provenance;
  - a limitation: what the value does NOT say.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import scoring, series as S
from .indicators import CMIP6, ERA5, Indicator, Provenance

MONTHS_EN = ["", "January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


@dataclass
class Hazard:
    key: str
    label: str
    score: float | None
    level: str
    headline: str
    primary_metric: str
    indicators: list[Indicator] = field(default_factory=list)
    limitation: str = ""
    projection: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["indicators"] = [i.to_dict() for i in self.indicators]
        d["scale"] = scoring.explain_breakpoints(self.key)
        d["scales"] = self.scales()
        return d

    def scales(self) -> list[dict]:
        """Geographic scales of the card's data, without repeats and in order.

        Contrast indicators, which do not score, do not count: heat does not become
        "provincial" because a regional level sits next to it.
        """
        out, seen = [], set()
        for ind in self.indicators:
            p = ind.provenance
            if not p.scale or ind.extras.get("contrast") or p.scale in seen:
                continue
            seen.add(p.scale)
            out.append({"label": p.scale, "kind": p.scale_kind})
        return out


def _era5_ind(key, label, value, unit, method, period, *, confidence="high", trend=None,
              significant=None, context=None, **extras) -> Indicator:
    return Indicator(
        key=key,
        label=label,
        value=None if value is None else round(value, 2),
        unit=unit,
        provenance=Provenance(period=period, method=method, confidence=confidence, **ERA5),
        trend_per_decade=None if trend is None else round(trend, 3),
        trend_significant=significant,
        context=context,
        extras=extras,
    )


def days_a_year(n: float, what: str) -> str:
    """"1 day a year", "less than one day a year": never "0 days" or "1 days"."""
    k = round(n)
    count = "Less than one day" if k == 0 else "1 day" if k == 1 else f"{k} days"
    return f"{count} a year {what}"


def count_phrase(n_per_year: float, what: str, months: set[int] | None) -> str:
    """All year: "6 days a year ...". Over a seasonal window the counts are annual
    equivalents, so they are said as a share of those days: "5 % of days in July ..."."""
    if not months:
        return days_a_year(n_per_year, what)
    pct = round(n_per_year / 365.25 * 100)
    window = " and ".join(MONTHS_EN[m] for m in sorted(months))
    return f"{'Less than 1 %' if pct == 0 else f'{pct} %'} of days in {window} {what}"


def _period(s: S.DailySeries) -> str:
    a, b = s.year_range
    return f"{a}-{b}"


# --------------------------------------------------------------------------- #
# Extreme heat
# --------------------------------------------------------------------------- #
def hazard_heat(recent: S.DailySeries, full: S.DailySeries,
                months: set[int] | None = None) -> Hazard:
    p_recent, p_full = _period(recent), _period(full)

    days35 = S.per_year(S.frequency(recent, "temperature_2m_max", lambda v: v >= 35))
    days32 = S.per_year(S.frequency(recent, "temperature_2m_max", lambda v: v >= 32))
    days40 = S.per_year(S.frequency(recent, "temperature_2m_max", lambda v: v >= 40))
    trop = S.per_year(S.frequency(recent, "temperature_2m_min", lambda v: v >= 20))
    record = max(S.clean(full.get("temperature_2m_max")), default=None)

    counts = S.annual_counts(full, "temperature_2m_max", lambda v: v >= 32)
    slope, sig = S.linear_trend(S.complete_years_only(full, {y: float(c) for y, c in counts.items()}))

    score = scoring.score_for("heat", days35)
    return Hazard(
        key="heat",
        label="Extreme heat",
        score=score,
        level=scoring.level_for(score),
        headline=(
            (count_phrase(days35, "above 35 degrees", months) if days35 else
             "35 degrees is practically never reached")
            # By the sea the heat that matters is often at night: a coastal town can
            # have less than one day above 35 °C and 55 tropical nights a year.
            + _tropical_clause(trop, months)
        ),
        primary_metric="hot_days_35",
        indicators=[
            _era5_ind("hot_days_35", "Days a year above 35 °C", days35,
                      "days/year", "mean number of days with temperature_2m_max >= 35 °C", p_recent),
            _era5_ind("hot_days_32", "Days a year above 32 °C", days32,
                      "days/year", "mean number of days with temperature_2m_max >= 32 °C", p_recent),
            _era5_ind("hot_days_40", "Days a year above 40 °C", days40,
                      "days/year", "mean number of days with temperature_2m_max >= 40 °C", p_recent),
            _era5_ind("tropical_nights", "Tropical nights (never below 20 °C)", trop,
                      "nights/year", "mean number of days with temperature_2m_min >= 20 °C", p_recent,
                      context="Warm nights prevent the body from recovering; they predict "
                              "mortality better than the daytime maximum"),
            _era5_ind("heat_record", "Highest temperature on record", record,
                      "°C", "absolute maximum of temperature_2m_max in the record", p_full),
            _era5_ind("hot_days_trend", "Trend in days above 32 °C", slope,
                      "days/decade", "linear regression on the annual count", p_full,
                      trend=slope, significant=sig, confidence="high" if sig else "medium"),
        ],
        limitation="ERA5 does not resolve the urban heat island: inside a dense city "
                   "the real temperature can be 2-5 °C above this figure.",
    )


# --------------------------------------------------------------------------- #
# Extreme rain (a proxy for surface-water flooding, NOT for river flooding)
# --------------------------------------------------------------------------- #
def hazard_rain(recent: S.DailySeries, full: S.DailySeries) -> Hazard:
    p_recent, p_full = _period(recent), _period(full)

    # RX1day (ETCCDI index): mean of the annual daily maxima. The 99th percentile of
    # ALL days collapses towards zero in the Mediterranean, where it does not rain on
    # 90 % of days, and hides exactly the event that matters.
    rx1_recent = S.complete_years_only(recent, S.annual_max(recent, "precipitation_sum"))
    rx1day = S.mean(list(rx1_recent.values()))

    p99 = S.percentile(recent.get("precipitation_sum"), 99)
    p999 = S.percentile(recent.get("precipitation_sum"), 99.9)
    record = max(S.clean(full.get("precipitation_sum")), default=None)
    heavy = S.per_year(S.frequency(recent, "precipitation_sum", lambda v: v >= 50))
    very_heavy = S.per_year(S.frequency(recent, "precipitation_sum", lambda v: v >= 100))

    slope, sig = S.linear_trend(
        S.complete_years_only(full, S.annual_max(full, "precipitation_sum"))
    )

    score = scoring.score_for("rain", rx1day)
    return Hazard(
        key="rain",
        label="Extreme rain",
        score=score,
        level=scoring.level_for(score),
        headline=(
            f"The wettest day of a typical year brings {rx1day:.0f} mm" if rx1day
            else "No precipitation data"
        ),
        primary_metric="rx1day",
        indicators=[
            _era5_ind("rx1day", "Rain on the wettest day of a typical year", rx1day,
                      "mm", "mean of the annual daily maxima of precipitation_sum "
                            "(ETCCDI RX1day index)", p_recent),
            _era5_ind("precip_record", "Highest daily rainfall on record", record, "mm",
                      "absolute maximum of precipitation_sum", p_full),
            _era5_ind("heavy_rain_days", "Days a year with more than 50 mm", heavy, "days/year",
                      "mean number of days with precipitation_sum >= 50 mm", p_recent),
            _era5_ind("torrential_days", "Days a year with more than 100 mm", very_heavy,
                      "days/year", "mean number of days with precipitation_sum >= 100 mm", p_recent),
            _era5_ind("precip_p99", "99th percentile daily rainfall", p99, "mm",
                      "99th percentile of precipitation_sum over all days", p_recent,
                      context="It also counts the days without rain, so in dry climates it "
                              "comes out much lower than intuition suggests"),
            _era5_ind("precip_p999", "99.9th percentile daily rainfall", p999, "mm",
                      "99.9th percentile of precipitation_sum", p_recent),
            _era5_ind("rx1day_trend", "Trend in extreme rain", slope,
                      "mm/decade", "linear regression on the annual daily maximum", p_full,
                      trend=slope, significant=sig, confidence="medium"),
        ],
        limitation="This measures RAIN, not FLOODING. Whether water builds up in your "
                   "street depends on the drains, the slope, how sealed the ground is "
                   "and the nearest watercourse, which needs a hydraulic model. For "
                   "official river flooding in Spain, see the SNCZI. ERA5 also averages "
                   "over ~9 km and therefore UNDERESTIMATES the peaks of a local "
                   "convective storm.",
    )


# --------------------------------------------------------------------------- #
# Fire weather danger
# --------------------------------------------------------------------------- #
def _fire_day(tmax, rhmin, wind, precip7) -> bool:
    return (
        tmax is not None and rhmin is not None and wind is not None
        and tmax >= 30 and rhmin <= 35 and wind >= 15
        and (precip7 is None or precip7 < 5)
    )


def _count_fire_days(s: S.DailySeries, strict: bool = False) -> tuple[float | None, int]:
    tmax = s.get("temperature_2m_max")
    rhmin = s.get("relative_humidity_2m_min")
    wind = s.get("wind_speed_10m_max")
    precip7 = s.get("precip_7d")
    valid = hits = 0
    for i in range(len(s)):
        if tmax[i] is None or rhmin[i] is None or wind[i] is None:
            continue
        valid += 1
        if strict:
            if tmax[i] >= 30 and rhmin[i] <= 30 and wind[i] >= 30:
                hits += 1
        elif _fire_day(tmax[i], rhmin[i], wind[i], precip7[i] if i < len(precip7) else None):
            hits += 1
    return (hits / valid if valid else None), hits


def _tropical_clause(trop: float | None, months: set[int] | None) -> str:
    if not trop:
        return ""
    if not months:
        return f"; {trop:.0f} tropical nights a year (the night never cools below 20 °C)" \
            if trop >= 10 else ""
    in_ten = round(trop / 365.25 * 10)
    return f"; {in_ten} in 10 nights never cool below 20 °C" if in_ten >= 2 else ""


def hazard_wildfire(recent: S.DailySeries, full: S.DailySeries,
                    months: set[int] | None = None) -> Hazard:
    p_recent, p_full = _period(recent), _period(full)
    freq, _ = _count_fire_days(recent)
    danger_days = S.per_year(freq)
    strict_freq, _ = _count_fire_days(recent, strict=True)
    strict_days = S.per_year(strict_freq)

    # Seasonality: which month concentrates the danger.
    by_month: dict[int, int] = {}
    tmax, rhmin, wind = (recent.get(k) for k in
                         ("temperature_2m_max", "relative_humidity_2m_min", "wind_speed_10m_max"))
    precip7 = recent.get("precip_7d")
    for i, d in enumerate(recent.dates):
        if _fire_day(tmax[i], rhmin[i], wind[i], precip7[i] if i < len(precip7) else None):
            by_month[d.month] = by_month.get(d.month, 0) + 1
    peak_month = max(by_month, key=by_month.get) if by_month else None

    annual: dict[int, float] = {d.year: 0.0 for d in full.dates}
    f_tmax, f_rh, f_wind = (full.get(k) for k in
                            ("temperature_2m_max", "relative_humidity_2m_min",
                             "wind_speed_10m_max"))
    f_p7 = full.get("precip_7d")
    for i, d in enumerate(full.dates):
        if _fire_day(f_tmax[i], f_rh[i], f_wind[i], f_p7[i] if i < len(f_p7) else None):
            annual[d.year] += 1.0
    slope, sig = S.linear_trend(S.complete_years_only(full, annual))

    score = scoring.score_for("wildfire", danger_days)
    return Hazard(
        key="wildfire",
        label="Wildfire danger",
        score=score,
        level=scoring.level_for(score),
        headline=(
            count_phrase(danger_days, "with fire-prone weather", months)
            # With less than one day a year "concentrated in February" is noise, and
            # over a one-month window it only repeats the month.
            + (f", concentrated in {MONTHS_EN[peak_month]}"
               if peak_month and danger_days is not None and danger_days >= 1
               and not (months and len(months) == 1) else "")
            if danger_days else "Weather rarely favours fire"
        ),
        primary_metric="fire_danger_days",
        indicators=[
            _era5_ind("fire_danger_days", "Days a year of high fire-weather danger",
                      danger_days, "days/year",
                      "days with Tmax >= 30 °C, minimum relative humidity <= 35 %, maximum "
                      "wind >= 15 km/h and less than 5 mm of rain in the previous 7 days",
                      p_recent, confidence="medium"),
            _era5_ind("fire_days_303030", "Days meeting the 30-30-30 rule",
                      strict_days, "days/year",
                      "days with Tmax >= 30 °C, minimum relative humidity <= 30 % and maximum "
                      "wind >= 30 km/h (operational rule of firefighting services)",
                      p_recent, confidence="medium"),
            _era5_ind("fire_peak_month", "Month of highest danger",
                      None if peak_month is None else float(peak_month), "(1-12)",
                      "month of the year with the most high-danger days", p_recent,
                      confidence="medium",
                      context=(f"The danger peaks in {MONTHS_EN[peak_month]}."
                               if peak_month else None)),
            _era5_ind("fire_days_trend", "Trend in danger days", slope,
                      "days/decade", "linear regression on the annual count", p_full,
                      trend=slope, significant=sig, confidence="medium" if sig else "low"),
        ],
        limitation="This is WEATHER danger, not wildfire risk. Real risk also depends "
                   "on fuel (what vegetation there is and how dry it is), terrain and "
                   "ignition, which in Europe is human in more than 90 % of cases. Where "
                   "the Copernicus projection is available (Spain), the card adds the "
                   "official projection of high-danger Fire Weather Index days.",
    )


# --------------------------------------------------------------------------- #
# CMIP6 projections
# --------------------------------------------------------------------------- #
def build_projection(base: S.DailySeries, future: S.DailySeries) -> dict:
    """Delta between two windows of the SAME set of models.

    The absolute value of a climate model is not a prediction; its change between two
    windows is informative, because the model bias cancels out.
    """
    def days35(s):
        return S.per_year(S.frequency(s, "temperature_2m_max", lambda v: v >= 35))

    def days32(s):
        return S.per_year(S.frequency(s, "temperature_2m_max", lambda v: v >= 32))

    def rx1day(s):
        return S.mean(list(S.complete_years_only(s, S.annual_max(s, "precipitation_sum")).values()))

    def delta(fn, key, unit):
        b, f = fn(base), fn(future)
        if b is None or f is None:
            return None
        return {
            "key": key,
            "baseline": round(b, 1),
            "future": round(f, 1),
            "delta": round(f - b, 1),
            "pct_change": None if b == 0 else round((f - b) / b * 100, 0),
            "unit": unit,
        }

    return {
        "baseline_period": _period(base),
        "future_period": _period(future),
        "scenario": "CMIP6 HighResMIP (highres-future, forcing close to SSP5-8.5)",
        "models": "multi-model mean",
        "provenance": {**CMIP6, "period": f"{_period(base)} vs {_period(future)}",
                       "method": "each model compared with itself between two windows; "
                                 "the delta is used, not the absolute value",
                       "confidence": "medium"},
        "metrics": [m for m in (
            delta(days35, "hot_days_35", "days/year"),
            delta(days32, "hot_days_32", "days/year"),
            delta(rx1day, "rx1day", "mm"),
        ) if m],
    }


PROJECTION_BY_HAZARD = {
    "heat": ("hot_days_35", "hot_days_32"),
    "rain": ("rx1day",),
}


def attach_projections(hazards: list[Hazard], projection: dict | None) -> None:
    if not projection:
        return
    by_key = {m["key"]: m for m in projection["metrics"]}
    for hazard in hazards:
        keys = PROJECTION_BY_HAZARD.get(hazard.key, ())
        metrics = [by_key[k] for k in keys if k in by_key]
        if metrics:
            hazard.projection = {
                "scenario": projection["scenario"],
                "baseline_period": projection["baseline_period"],
                "future_period": projection["future_period"],
                "provenance": projection["provenance"],
                "metrics": metrics,
            }
