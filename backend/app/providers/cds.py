"""Copernicus Climate Data Store (CDS) and CEMS Early Warning Data Store (EWDS).

The CDS is not a query API: it is a batch job queue shared by the whole scientific
community, and a small request can take from minutes to hours. This module is therefore
NEVER called from the path of a user request. It is used in two ways:

  1. From `backend/scripts/cds_download.py` and `cds_hazards.py`, in batch, to build
     the local layers that ARE queried in milliseconds.
  2. From `/api/cds/jobs`, asynchronously: a job is submitted, an id is returned and
     its status can be polled. No response ever waits for it.

Configuration (the first wins):
  - CDS_API_KEY (and EWDS_API_KEY for the emergency store) in the environment or .env.
  - The ~/.cdsapirc file:
        url: https://cds.climate.copernicus.eu/api
        key: <PERSONAL-ACCESS-TOKEN>

Each dataset's terms of use must be accepted by hand on its web page, or the retrieve
fails with a 403.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

import httpx

from .. import config

Store = Literal["cds", "ewds"]

DATASET_DAILY_STATS = "derived-era5-single-levels-daily-statistics"
DATASET_FIRE_HISTORICAL = "cems-fire-historical-v1"
# In the CDS, with the same account as ERA5 (the EWDS account is not needed).
DATASET_FIRE_PROJECTIONS = "sis-tourism-fire-danger-indicators"

_ALL_DAYS = [f"{d:02d}" for d in range(1, 32)]
_ALL_MONTHS = [f"{m:02d}" for m in range(1, 13)]

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cds")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_JOBS_FILE = config.CDS_DIR / "jobs.json"


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def _read_cdsapirc() -> dict[str, str]:
    path = Path.home() / ".cdsapirc"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def credentials(store: Store = "cds") -> tuple[str | None, str | None]:
    """(url, key) for the requested store, or (url, None) if the key is missing."""
    if store == "ewds":
        return config.EWDS_URL, config.EWDS_KEY
    if config.CDS_KEY:
        return config.CDS_URL, config.CDS_KEY
    rc = _read_cdsapirc()
    return rc.get("url", config.CDS_URL), rc.get("key")


def credentials_status() -> dict:
    """A diagnosis safe to expose through the API: it never reveals the token."""
    out = {}
    for store in ("cds", "ewds"):
        url, key = credentials(store)  # type: ignore[arg-type]
        out[store] = {
            "url": url,
            "configured": bool(key),
            "key_hint": f"...{key[-4:]}" if key else None,
            "source": (
                "environment variable"
                if (store == "cds" and config.CDS_KEY)
                or (store == "ewds" and config.EWDS_KEY)
                else ("~/.cdsapirc" if key else "not configured")
            ),
        }
    out["client"] = "native REST (httpx) against OGC API - Processes"
    return out


class CdsError(RuntimeError):
    """A CDS error with the response body already included."""


def describe_error(exc: Exception, dataset: str, store: Store) -> str:
    """Turns an HTTP error into something actionable.

    The real reason of a 403 is in the response BODY, and it is almost always one of
    three: the dataset's licence not accepted, a request too large ("cost limits
    exceeded") or too many queued jobs.
    """
    parts = [f"{type(exc).__name__}: {exc}"]
    response = getattr(exc, "response", None)
    body = ""
    if response is not None:
        try:
            body = response.text[:600]
        except Exception:  # noqa: BLE001
            body = ""
        if body:
            parts.append(f"server response: {body}")

    status = getattr(response, "status_code", None)
    host = credentials(store)[0].rsplit("/api", 1)[0]
    if "cost limits" in body or "too large" in body:
        parts.append(
            "The request is too large for the CDS. Split it: --years-per-request 1 in "
            "cds_download.py. The CDS returns this as a 403, which looks like a "
            "permissions problem and is not."
        )
    elif "queued requests" in body:
        parts.append(
            "Limit of queued jobs for this dataset. Lower --max-in-flight; it is not an "
            "error in the request and it can be retried."
        )
    elif status == 403 or "403" in str(exc):
        parts.append(
            "Usual cause: the terms of use of THIS dataset have not been accepted. They are "
            f"accepted one by one: go to {host}/datasets/{dataset}?tab=download, scroll to "
            "'Terms of use' and click 'Accept'. If they are accepted, check that the token "
            f"is the one from {host}/profile."
        )
    elif status == 401:
        parts.append(f"Invalid or expired token. Copy it again from {host}/profile.")
    elif status == 404:
        parts.append(
            f"The dataset '{dataset}' does not exist on {host}. The emergency datasets "
            "(fire, flood) live on ewds.climate.copernicus.eu and use another account."
        )
    return " | ".join(parts)


def _auth(store: Store) -> tuple[str, dict[str, str]]:
    """API base and authentication headers.

    The REST API (OGC API - Processes) is called directly instead of through `cdsapi`
    for two reasons: the body of error responses stays readable (a cost-limit 403
    explains itself), and separating submit / poll / download lets several jobs queue
    in parallel instead of waiting in line.
    """
    url, key = credentials(store)
    if not key:
        raise CdsError(
            f"the {store.upper()} token is missing. Put it in {store.upper()}_API_KEY in "
            f"the project's .env or in ~/.cdsapirc. Get it from "
            f"{(url or '').rsplit('/api', 1)[0]}/profile"
        )
    return url.rstrip("/"), {
        "PRIVATE-TOKEN": key,
        "Accept": "application/json",
        "User-Agent": config.USER_AGENT,
    }


def _raise_for_status(response, dataset: str, store: Store) -> None:
    if response.status_code < 400:
        return
    body = response.text[:600]
    exc = CdsError(f"HTTP {response.status_code}")
    exc.response = response  # type: ignore[attr-defined]
    raise CdsError(describe_error(exc, dataset, store) + (f" | body: {body}" if body else ""))


def submit_job(dataset: str, request: dict, *, store: Store = "cds") -> str:
    """Queues the job and returns its jobID. It does not wait."""
    base, headers = _auth(store)
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{base}/retrieve/v1/processes/{dataset}/execution",
            headers=headers,
            json={"inputs": request},
        )
    _raise_for_status(resp, dataset, store)
    return resp.json()["jobID"]


def job_status(job_id: str, *, store: Store = "cds") -> dict:
    base, headers = _auth(store)
    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{base}/retrieve/v1/jobs/{job_id}", headers=headers)
    _raise_for_status(resp, job_id, store)
    return resp.json()


def job_result_href(job_id: str, *, store: Store = "cds") -> tuple[str, int | None]:
    base, headers = _auth(store)
    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{base}/retrieve/v1/jobs/{job_id}/results", headers=headers)
    _raise_for_status(resp, job_id, store)
    asset = resp.json().get("asset", {}).get("value", {})
    href = asset.get("href")
    if not href:
        raise CdsError(f"job {job_id} finished without a downloadable file: {resp.text[:300]}")
    return href, asset.get("file:size")


def download_href(href: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with httpx.Client(timeout=None, follow_redirects=True) as client:
        with client.stream("GET", href) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
    tmp.replace(target)
    return target


# --------------------------------------------------------------------------- #
# Request builders
# --------------------------------------------------------------------------- #
def bbox_around(lat: float, lon: float, half_deg: float = 0.75) -> list[float]:
    """Box [north, west, south, east] around a point: ~3 ERA5 cells each way."""
    return [
        round(min(90.0, lat + half_deg), 2),
        round(max(-180.0, lon - half_deg), 2),
        round(max(-90.0, lat - half_deg), 2),
        round(min(180.0, lon + half_deg), 2),
    ]


def build_daily_stats_request(
    *,
    variable: str | list[str],
    years: list[int],
    daily_statistic: str = "daily_maximum",
    months: list[str] | None = None,
    area: list[float] | None = None,
) -> dict[str, Any]:
    """Request for `derived-era5-single-levels-daily-statistics`.

    The daily aggregation is done server-side, so ~24 times less is downloaded than
    with hourly ERA5 and the queue is shorter.
    """
    request: dict[str, Any] = {
        "product_type": "reanalysis",
        "variable": [variable] if isinstance(variable, str) else list(variable),
        "year": [str(y) for y in years],
        "month": months or _ALL_MONTHS,
        "day": _ALL_DAYS,
        "daily_statistic": daily_statistic,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
    }
    if area:
        request["area"] = area
    return request


def build_fire_request(
    *,
    years: list[int],
    variable: str = "fire_weather_index",
    months: list[str] | None = None,
    area: list[float] | None = None,
) -> dict[str, Any]:
    """Request for the CEMS historical Fire Weather Index (EWDS, another account).

    Check `system_version` and `dataset_type` against the dataset's Download tab before
    using it: they change between versions.
    """
    request: dict[str, Any] = {
        "product_type": ["reanalysis"],
        "variable": [variable],
        "dataset_type": "consolidated_dataset",
        "system_version": ["4_1"],
        "year": [str(y) for y in years],
        "month": months or _ALL_MONTHS,
        "day": _ALL_DAYS,
        "grid": "0.25/0.25",
        "data_format": "netcdf",
    }
    if area:
        request["area"] = area
    return request


def build_fire_projection_request(*, experiment: str, period: str) -> dict[str, Any]:
    """Days with high and very high fire danger (FWI, EFFIS), EURO-CORDEX.

    The dataset does not support cropping by area: the file is the whole of Europe. The
    20-year periods (1981_2005, 2041_2060) only exist in version v1_0.
    """
    return {
        "time_aggregation": "annual_indicators",
        "product_type": "multi_model_mean_case",
        "variable": ["number_of_days_with_high_fire_danger",
                     "number_of_days_with_very_high_fire_danger"],
        "experiment": experiment,
        "period": [period],
        "version": "v1_0",
    }


# --------------------------------------------------------------------------- #
# Synchronous execution (batch scripts)
# --------------------------------------------------------------------------- #
def retrieve(
    dataset: str,
    request: dict,
    target: Path | str,
    *,
    store: Store = "cds",
    on_log=None,
    poll_seconds: float = 15.0,
    max_wait_seconds: float = 4 * 3600,
) -> Path:
    """Queues, polls until the CDS serves it, and downloads.

    It blocks, potentially for hours: only from scripts or from the background thread of
    `submit()`. If `max_wait_seconds` runs out nothing is lost: the job stays alive in
    the CDS and can be collected later with its jobID.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    log = on_log or (lambda _m: None)

    job_id = submit_job(dataset, request, store=store)
    log(f"queued in {store}: job {job_id}")

    started = time.monotonic()
    last_status = ""
    while True:
        info = job_status(job_id, store=store)
        status = info.get("status", "?")
        if status != last_status:
            log(f"[{time.monotonic() - started:6.0f}s] status: {status}")
            last_status = status
        if status == "successful":
            break
        if status in ("failed", "dismissed"):
            raise CdsError(f"job {job_id} ended as '{status}'. Details: {json.dumps(info)[:500]}")
        if time.monotonic() - started > max_wait_seconds:
            raise CdsError(
                f"job {job_id} is still '{status}' after {max_wait_seconds / 60:.0f} min. It is "
                f"not lost: it is still in the CDS queue and can be collected with its jobID."
            )
        time.sleep(poll_seconds)

    href, size = job_result_href(job_id, store=store)
    log(f"downloading {(size or 0) / 1e6:.1f} MB")
    download_href(href, target)
    log(f"<- {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


_PENDING_FILE = config.CDS_DIR / "pending.json"


def _load_pending() -> dict[str, dict]:
    if not _PENDING_FILE.exists():
        return {}
    try:
        return json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def remember_pending(job_id: str, dataset: str, target: Path, store: Store) -> None:
    """Records which file a queued job corresponds to.

    With queues that can take hours, the realistic pattern is submit today and collect
    tomorrow; the CDS does not say which job was going to be which file, so it is
    remembered here.
    """
    pending = _load_pending()
    pending[job_id] = {
        "dataset": dataset,
        "target": str(target),
        "store": store,
        "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    _PENDING_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")


def forget_pending(job_id: str) -> None:
    pending = _load_pending()
    if pending.pop(job_id, None) is not None:
        _PENDING_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")


def pending_jobs() -> dict[str, dict]:
    """Submitted jobs whose file is not on disk yet."""
    return {
        job_id: info for job_id, info in _load_pending().items()
        if not Path(info["target"]).exists()
    }


def account_jobs(*, store: Store = "cds", limit: int = 50) -> dict:
    """The account's jobs in the CDS, with how long they have been waiting (GET only)."""
    base, headers = _auth(store)
    with httpx.Client(timeout=40) as client:
        resp = client.get(f"{base}/retrieve/v1/jobs", headers=headers, params={"limit": limit})
    _raise_for_status(resp, "jobs", store)

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    rows, by_status = [], {}
    for job in resp.json().get("jobs", []):
        status = job.get("status", "?")
        by_status[status] = by_status.get(status, 0) + 1
        created = job.get("created", "")
        waited = None
        if created:
            try:
                waited = round(
                    (now - dt.datetime.fromisoformat(created.replace("Z", ""))).total_seconds() / 60, 1)
            except ValueError:
                waited = None
        rows.append({
            "job_id": job.get("jobID", "")[:8],
            "dataset": job.get("processID"),
            "status": status,
            "created": created[:19],
            "waiting_minutes": waited,
        })

    waiting = [r["waiting_minutes"] for r in rows
               if r["status"] in ("accepted", "running") and r["waiting_minutes"]]
    return {
        "store": store,
        "counts": by_status,
        "longest_wait_minutes": max(waiting) if waiting else None,
        "jobs": rows[:limit],
        "note": "A job in 'accepted' has not started processing yet.",
    }


def retrieve_many(
    jobs: list[tuple[str, dict, Path]],
    *,
    store: Store = "cds",
    on_log=None,
    poll_seconds: float = 20.0,
    max_wait_seconds: float = 4 * 3600,
    max_in_flight: int = 2,
    max_retries: int = 6,
) -> dict[str, Path | None]:
    """Queues every job within a window and downloads them as they finish.

    Two CDS limits govern this loop:
      - Size: a large request is rejected with a 403 "cost limits exceeded", so the
        caller splits by years.
      - Queue: there is a maximum of queued requests per dataset and user; above it
        jobs come back 'rejected'. That is not an error in the request: it is retried.

    Returns {file name: downloaded path, or None if it failed}.
    """
    log = on_log or (lambda _m: None)
    todo: list[tuple[str, dict, Path, int]] = []
    results: dict[str, Path | None] = {}

    for dataset, request, target in jobs:
        if target.exists():
            log(f"[skipped] {target.name} already exists")
            results[target.name] = target
        else:
            todo.append((dataset, request, target, 0))

    in_flight: dict[str, tuple[str, dict, Path, int]] = {}
    seen: dict[str, str] = {}
    started = time.monotonic()

    while todo or in_flight:
        if time.monotonic() - started > max_wait_seconds:
            for job_id, (_d, _r, target, _a) in in_flight.items():
                log(f"[timed out] {target.name} is still alive in the CDS as {job_id}")
                results[target.name] = None
            for _d, _r, target, _a in todo:
                log(f"[timed out] {target.name} was never submitted")
                results[target.name] = None
            break

        while todo and len(in_flight) < max_in_flight:
            dataset, request, target, attempts = todo.pop(0)
            try:
                job_id = submit_job(dataset, request, store=store)
            except CdsError as exc:
                log(f"[failed to queue] {target.name}: {exc}")
                results[target.name] = None
                continue
            in_flight[job_id] = (dataset, request, target, attempts)
            remember_pending(job_id, dataset, target, store)
            log(f"[queued {len(in_flight)}/{max_in_flight}] {target.name}  job {job_id}")

        for job_id in list(in_flight):
            dataset, request, target, attempts = in_flight[job_id]
            try:
                status = job_status(job_id, store=store).get("status", "?")
            except CdsError as exc:
                log(f"[failed to poll] {target.name}: {exc}")
                results[target.name] = None
                in_flight.pop(job_id)
                continue

            if seen.get(job_id) != status:
                log(f"[{time.monotonic() - started:5.0f}s] {target.name}: {status}")
                seen[job_id] = status

            if status == "successful":
                try:
                    href, _size = job_result_href(job_id, store=store)
                    download_href(href, target)
                    log(f"[done] {target.name} ({target.stat().st_size / 1e6:.2f} MB)")
                    results[target.name] = target
                    forget_pending(job_id)
                except Exception as exc:  # noqa: BLE001
                    log(f"[failed to download] {target.name}: {exc}")
                    results[target.name] = None
                in_flight.pop(job_id)

            elif status == "rejected":
                in_flight.pop(job_id)
                if attempts + 1 <= max_retries:
                    log(f"[rejected] {target.name}: queue full, retry {attempts + 1}/{max_retries}")
                    todo.append((dataset, request, target, attempts + 1))
                else:
                    log(f"[failed] {target.name}: rejected {max_retries} times in a row")
                    results[target.name] = None

            elif status in ("failed", "dismissed"):
                log(f"[failed] {target.name}: the CDS left it as '{status}'")
                results[target.name] = None
                in_flight.pop(job_id)

        if todo or in_flight:
            time.sleep(poll_seconds)

    return results


# --------------------------------------------------------------------------- #
# Asynchronous execution (the API)
# --------------------------------------------------------------------------- #
def _persist_jobs() -> None:
    with _jobs_lock:
        snapshot = json.dumps(_jobs, indent=2, default=str)
    _JOBS_FILE.write_text(snapshot, encoding="utf-8")


def _update(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)
    _persist_jobs()


def load_jobs() -> dict[str, dict]:
    """Recovers the job register after a server restart."""
    global _jobs
    if _JOBS_FILE.exists() and not _jobs:
        try:
            _jobs = json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _jobs = {}
    return _jobs


def submit(dataset: str, request: dict, *, store: Store = "cds", label: str = "") -> dict:
    """Queues the job in a thread and returns its record straight away."""
    job_id = uuid.uuid4().hex[:12]
    target = config.CDS_DIR / f"{job_id}.nc"
    record = {
        "id": job_id,
        "label": label or dataset,
        "store": store,
        "dataset": dataset,
        "request": request,
        "status": "queued",
        "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "finished_at": None,
        "target": str(target),
        "size_bytes": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = record
    _persist_jobs()

    def _run():
        started = dt.datetime.now(dt.timezone.utc)
        _update(job_id, status="running", started_at=started.isoformat())
        try:
            retrieve(dataset, request, target, store=store)
            _update(
                job_id,
                status="completed",
                finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                size_bytes=target.stat().st_size,
                elapsed_seconds=round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
            )
        except Exception as exc:  # noqa: BLE001 - the reason goes in the record
            _update(
                job_id,
                status="failed",
                finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                error=f"{type(exc).__name__}: {exc}",
                elapsed_seconds=round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
            )

    _executor.submit(_run)
    return record


def job(job_id: str) -> dict | None:
    load_jobs()
    with _jobs_lock:
        return _jobs.get(job_id)


def all_jobs() -> list[dict]:
    load_jobs()
    with _jobs_lock:
        return sorted(_jobs.values(), key=lambda j: j.get("submitted_at", ""), reverse=True)
