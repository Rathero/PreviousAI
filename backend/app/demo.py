"""The demo home: every answer built once, ahead of time, and served from disk.

A demonstration cannot wait, and it cannot afford a value that moves between the
rehearsal and the room. Most of a report is climatology and is cached for a month, but
alerts expire in half an hour and the forecast in three: when one of them moves the
report moves with it, the briefing is a different video and has to be encoded again, and
a street simulation drawn for "low" stops being shown because the card now says
"moderate". So for the addresses listed here everything is built once, by
`backend/scripts/demo_build.py`, and kept in `data/demo`:

    report + app view   ->  /api/report answers from the file
    PDF                 ->  /api/report/pdf sends the bytes drawn that day
    briefing            ->  /api/briefing answers "done" with the MP4 already rendered
    location            ->  /api/locate, and the address is offered while typing

Nothing here invents anything. A pack is an ordinary report, built by the same code from
the same sources, and it carries the moment it was built (`meta.generated_at`), so what
it says about right now is dated rather than pretended. Any address that is not pinned,
and every pinned one when PREVIOUS_DEMO=0, goes through the live path as before.

The homes are the ones simulations.py draws the four hazards for on a photo of their own
street: a demonstration wants both, and the coordinates then live in one place.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

from . import config, dwelling as DW, simulations

DIR = config.DATA_DIR / "demo"
INDEX = DIR / "index.json"
VERSION = 1

# What else a pinned home answers to. "Garona" is the river the avenue follows and
# "Dera Garona" its name in Aranese, which is how the Spanish address service spells it;
# all of these resolve to this street, which is the precision the report has here.
# `place` is what the dropdown shows under the address, as CartoCiudad writes it.
HOMES = {
    "vielha-avinguda-garona": {
        "place": "25530, Vielha, Lleida",
        "aliases": (
            "Avinguda Garona, Vielha",
            "Avinguda Garona 10, Vielha e Mijaran",
            "Avinguda Garona, Vielha e Mijaran, Spain",
            "Avinguda Dera Garona 10, Vielha",
            "Avinguda dera Garona, Vielha",
            "Avenida Garona 10, Vielha",
        ),
    },
}


def enabled() -> bool:
    """PREVIOUS_DEMO=0 puts every pinned address back on the live path."""
    return config.DEMO_PINNED


# --------------------------------------------------------------------------- #
# Which address, which home
# --------------------------------------------------------------------------- #
def normalise(text: str | None) -> str:
    """"Avinguda Garona 10, Vielha" and "avinguda  garona 10 vielha" are one address."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


def _spellings(place_id: str) -> list[str]:
    place = simulations.PLACES[place_id]
    return [place["query"], place["label"], *(HOMES.get(place_id, {}).get("aliases") or ())]


def match(address: str | None) -> str | None:
    """The pinned home an address asks for, or None."""
    typed = normalise(address)
    if not typed:
        return None
    return next((pid for pid in simulations.PLACES
                 if any(normalise(s) == typed for s in _spellings(pid))), None)


def match_point(lat: float, lon: float) -> str | None:
    """The pinned home a point falls on: the briefing is asked for by coordinates."""
    return simulations.place_at(lat, lon)


def suggestion(query: str) -> dict | None:
    """The pinned address as an entry for the address box, while what is typed is still
    the start of it. The service that suggests Spanish addresses knows this street by its
    Aranese name and at other numbers, so without this the demo address is one the
    dropdown never offers."""
    typed = normalise(query)
    if len(typed) < 3:
        return None
    for pid, place in simulations.PLACES.items():
        if any(normalise(s).startswith(typed) for s in _spellings(pid)):
            return {"text": place["query"], "line1": place["query"].rsplit(",", 1)[0].strip(),
                    "line2": HOMES.get(pid, {}).get("place") or place["label"],
                    "precision": "street"}
    return None


def variant(home: str | None, floor: str | int | None, who: list[str] | None) -> str:
    """The name of the pack a request asks for: the home and the household change the
    report, so each combination is its own pack."""
    dw = DW.parse(home, floor)
    if dw is None:
        parts = ["any"]
    elif dw["kind"] == "apartment" and dw["floor"] is not None:
        parts = [f"apartment-{dw['floor']}"]
    else:
        parts = [dw["kind"]]
    return "_".join(parts + sorted(who or []))


# --------------------------------------------------------------------------- #
# The packs on disk
# --------------------------------------------------------------------------- #
_index: tuple[float, dict] | None = None
_files: dict[str, tuple[float, object]] = {}


def index() -> dict:
    """data/demo/index.json, re-read when it changes."""
    global _index
    try:
        mtime = INDEX.stat().st_mtime
    except OSError:
        return {"version": VERSION, "packs": {}}
    if _index and _index[0] == mtime:
        return _index[1]
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if data.get("version") != VERSION:
        data = {"version": VERSION, "packs": {}}
    data.setdefault("packs", {})
    _index = (mtime, data)
    return data


def pack(place_id: str | None, variant_id: str) -> dict | None:
    """What was built for this home and this household, or None."""
    if not place_id or not enabled():
        return None
    return ((index()["packs"].get(place_id) or {}).get("variants") or {}).get(variant_id)


def _path(rel: str | None) -> Path | None:
    """A file of a pack, while it is there. The index names it; the file is what counts."""
    if not rel:
        return None
    path = (DIR / rel).resolve()
    return path if DIR.resolve() in path.parents and path.is_file() else None


def _read(rel: str | None, *, binary: bool = False):
    """A file of a pack, kept in memory until it is rebuilt."""
    path = _path(rel)
    if path is None:
        return None
    mtime = path.stat().st_mtime
    hit = _files.get(rel)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        value = path.read_bytes() if binary else json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _files[rel] = (mtime, value)
    return value


def report(entry: dict) -> dict | None:
    return _read(entry.get("report"))


def view(entry: dict) -> dict | None:
    """The app's report, with a note of what else is already made: the page uses it to
    fetch the briefing before anyone asks for it."""
    body = _read(entry.get("view"))
    if body is None:
        return None
    ready = briefing(entry)
    return {**body, "pinned": {"built_at": entry.get("built_at"),
                               "briefing_id": (ready or {}).get("id"),
                               "briefing_video": (ready or {}).get("video"),
                               "pdf": _path(entry.get("pdf")) is not None}}


def pdf(entry: dict) -> tuple[bytes, str] | None:
    body = _read(entry.get("pdf"), binary=True)
    return (body, entry.get("pdf_filename") or "previous-ai-report.pdf") if body else None


def briefing(entry: dict) -> dict | None:
    """The briefing record, only while its MP4 is still on disk."""
    from . import briefing as B

    record = _read(entry.get("briefing"))
    if not record or not B.file_path(record.get("video", "")):
        return None
    return record


# --------------------------------------------------------------------------- #
# Writing a pack (backend/scripts/demo_build.py)
# --------------------------------------------------------------------------- #
def write(place_id: str, variant_id: str, *, report_body: dict, view_body: dict,
          pdf_bytes: bytes | None, pdf_filename: str | None,
          briefing_record: dict | None) -> dict:
    """Saves one home's pack and adds it to the index. Returns its entry."""
    folder = Path(place_id) / variant_id
    (DIR / folder).mkdir(parents=True, exist_ok=True)

    def put(name: str, data) -> str:
        path = DIR / folder / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        if isinstance(data, bytes):
            tmp.write_bytes(data)
        else:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return folder.joinpath(name).as_posix()

    entry = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "report_generated_at": (report_body.get("meta") or {}).get("generated_at"),
        "report": put("report.json", report_body),
        "view": put("view.json", view_body),
        "pdf": put("report.pdf", pdf_bytes) if pdf_bytes else None,
        "pdf_filename": pdf_filename,
        "pdf_bytes": len(pdf_bytes) if pdf_bytes else 0,
        "briefing": put("briefing.json", briefing_record) if briefing_record else None,
        "briefing_id": (briefing_record or {}).get("id"),
        "briefing_video": (briefing_record or {}).get("video"),
        "narrated": (briefing_record or {}).get("narrated"),
    }
    place = simulations.PLACES[place_id]
    data = json.loads(json.dumps(index()))   # a copy: the cached index must not be edited
    saved = data.setdefault("packs", {}).setdefault(
        place_id, {"query": place["query"], "label": place["label"],
                   "latitude": place["lat"], "longitude": place["lon"], "variants": {}})
    saved.setdefault("variants", {})[variant_id] = entry
    data["version"] = VERSION
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(INDEX)
    return entry


# --------------------------------------------------------------------------- #
# What is ready, and how old it is
# --------------------------------------------------------------------------- #
def status() -> dict:
    """For /api/health and for checking before a demonstration: every pinned home, what
    it has, and the age in hours of the oldest pack."""
    now = dt.datetime.now(dt.timezone.utc)
    packs = index()["packs"]
    homes, oldest = [], None
    for place_id, place in simulations.PLACES.items():
        variants = (packs.get(place_id) or {}).get("variants") or {}
        for variant_id, entry in sorted(variants.items()):
            try:
                age = (now - dt.datetime.fromisoformat(entry["built_at"])).total_seconds() / 3600
            except (KeyError, TypeError, ValueError):
                age = None
            if age is not None:
                oldest = age if oldest is None else max(oldest, age)
            homes.append({
                "place": place_id, "query": place["query"], "variant": variant_id,
                "built_at": entry.get("built_at"),
                "age_hours": None if age is None else round(age, 1),
                "report": _path(entry.get("view")) is not None,
                "pdf": _path(entry.get("pdf")) is not None,
                "briefing": briefing(entry) is not None,
            })
    return {"enabled": enabled(), "homes": homes,
            "oldest_hours": None if oldest is None else round(oldest, 1)}
