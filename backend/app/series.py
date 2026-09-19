"""Statistics over daily series.

Deliberately pure Python: the request path needs neither numpy nor pandas.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass


@dataclass
class DailySeries:
    dates: list[dt.date]
    vars: dict[str, list[float | None]]

    @classmethod
    def from_open_meteo(cls, payload: dict) -> "DailySeries":
        daily = payload["daily"]
        dates = [dt.date.fromisoformat(d) for d in daily["time"]]
        vars_ = {k: v for k, v in daily.items() if k != "time"}
        return cls(dates=dates, vars=vars_)

    def __len__(self) -> int:
        return len(self.dates)

    def get(self, name: str) -> list[float | None]:
        return self.vars.get(name, [None] * len(self.dates))

    def subset(self, *, months: set[int] | None = None, min_year: int | None = None) -> "DailySeries":
        idx = [
            i
            for i, d in enumerate(self.dates)
            if (months is None or d.month in months)
            and (min_year is None or d.year >= min_year)
        ]
        return DailySeries(
            dates=[self.dates[i] for i in idx],
            vars={k: [v[i] for i in idx] for k, v in self.vars.items()},
        )

    @property
    def year_range(self) -> tuple[int, int]:
        return (self.dates[0].year, self.dates[-1].year) if self.dates else (0, 0)


def clean(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def percentile(values: list[float | None], p: float) -> float | None:
    """Percentile by linear interpolation (R's method 7)."""
    xs = sorted(clean(values))
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def mean(values: list[float | None]) -> float | None:
    xs = clean(values)
    return sum(xs) / len(xs) if xs else None


def annual_counts(series: DailySeries, variable: str, predicate) -> dict[int, int]:
    """How many days per year meet the condition."""
    values = series.get(variable)
    out: dict[int, int] = {}
    for date, value in zip(series.dates, values):
        out.setdefault(date.year, 0)
        if value is not None and predicate(value):
            out[date.year] += 1
    return out


def annual_days_available(series: DailySeries) -> dict[int, int]:
    out: dict[int, int] = {}
    for date in series.dates:
        out[date.year] = out.get(date.year, 0) + 1
    return out


def frequency(series: DailySeries, variable: str, predicate) -> float | None:
    """Fraction of valid days that meet the condition."""
    values = clean(series.get(variable))
    if not values:
        return None
    hits = sum(1 for v in values if predicate(v))
    return hits / len(values)


def per_year(freq: float | None) -> float | None:
    """Fraction of days -> equivalent days per year.

    The same number works over the whole calendar and over a seasonal window
    (equivalent days a year if the whole year were like that window), so scores stay
    comparable.
    """
    return None if freq is None else freq * 365.25


def linear_trend(points: dict[int, float]) -> tuple[float | None, bool]:
    """Least-squares slope per decade and whether it is significant.

    Significance is a t-test on the correlation with alpha ~0.05: enough to decide
    whether a trend is worth mentioning.
    """
    items = sorted(points.items())
    n = len(items)
    if n < 10:
        return None, False
    xs = [float(y) for y, _ in items]
    ys = [float(v) for _, v in items]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None, False
    slope = sxy / sxx
    r = sxy / math.sqrt(sxx * syy)
    if abs(r) >= 0.999:
        return slope * 10.0, True
    t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
    return slope * 10.0, t > 2.0


def complete_years_only(series: DailySeries, values: dict[int, float]) -> dict[int, float]:
    """Drops years with an incomplete series before computing trends: the first and last
    years of a record are almost always truncated and would put a false step in it."""
    available = annual_days_available(series)
    if not available:
        return {}
    expected = sorted(available.values())[len(available) // 2]
    threshold = expected * 0.95
    return {y: v for y, v in values.items() if available.get(y, 0) >= threshold}


def annual_max(series: DailySeries, variable: str) -> dict[int, float]:
    """Maximum of each year. With precipitation this is the ETCCDI RX1day index."""
    values = series.get(variable)
    out: dict[int, float] = {}
    for date, value in zip(series.dates, values):
        if value is not None:
            prev = out.get(date.year)
            if prev is None or value > prev:
                out[date.year] = value
    return out


def extreme_days(series: DailySeries, variable: str, *, top: int = 5,
                 largest: bool = True) -> list[dict]:
    """The N most extreme days of the series."""
    pairs = [(d, v) for d, v in zip(series.dates, series.get(variable)) if v is not None]
    pairs.sort(key=lambda p: p[1], reverse=largest)
    return [{"date": d.isoformat(), "value": round(v, 1)} for d, v in pairs[:top]]


def rolling_sum(values: list[float | None], window: int) -> list[float | None]:
    """Backward rolling sum (the rain of the previous days, for the fire-weather proxy)."""
    out: list[float | None] = []
    acc = 0.0
    queue: list[float] = []
    for v in values:
        queue.append(v if v is not None else 0.0)
        acc += queue[-1]
        if len(queue) > window:
            acc -= queue.pop(0)
        out.append(acc if len(queue) == window else None)
    return out
