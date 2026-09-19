"""Generates a place's simulations with fal.ai (batch, once): its four risks on its photo.

The report for the place is built first (from the cache when it is warm), and each risk
tile's data write its prompt (app/simulations.py). Each prompt becomes an edit of the
street photo and then a 5-second clip, re-encoded to a light web size and recorded in
data/media/places/manifest.json with the level, the value, the models and the prompts.
Reports only look the clips up; nothing is generated on the user's path.

    python backend/scripts/fal_place.py --photo street.png --dry-run   # prompts and cost
    python backend/scripts/fal_place.py --stills-only                  # review the stills first
    python backend/scripts/fal_place.py                                # everything still missing
    python backend/scripts/fal_place.py --only flood --force           # a new still and clip

The photo is kept in the place's raw/ folder, which is not versioned. It is resumable:
a risk already drawn at its current level is skipped (unless --force). Needs FAL_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import mimetypes
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "°".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import config, report as R, simulations as SIM, video, view  # noqa: E402
from app.providers import fal  # noqa: E402

SEED = 20260919
VIDEO_SECONDS = 5


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(key: str, text: str) -> None:
    print(f"  {key:<10} {text}")


def photo_path(folder: Path) -> Path | None:
    return next(iter(sorted((folder / "raw").glob("photo.*"))), None)


async def upload(path: Path) -> str:
    kind = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return await fal.upload(path.read_bytes(), kind, path.name, expires_in="1d")


async def make_still(pid: str, key: str, spec: dict, tile: dict, seed: int, photo_url: str,
                     man: dict, model: str | None) -> Path:
    folder = SIM.LIBRARY_DIR / pid
    path = folder / "stills" / f"{key}.jpg"
    log(key, f"editing the photo ({tile['level']}, {tile['score']}/100)…")
    out = await fal.edit(photo_url, spec["image"], seed=seed, model=model)
    path.write_bytes(await fal.download(out["url"]))
    man["places"][pid]["scenes"][key] = {
        "key": key, "level": tile["level"], "score": tile["score"], "what": spec["what"],
        "chosen_by": spec["chosen_by"], "still": f"{pid}/stills/{path.name}",
        "image_model": out["model"], "image_prompt": spec["image"], "seed": seed,
        "still_generated_at": now()}
    SIM.save_manifest(man)
    log(key, f"still ok ({out['elapsed_ms'] / 1000:.0f} s) → {path.relative_to(config.ROOT)}")
    return path


async def make_clip(pid: str, key: str, spec: dict, still: Path, man: dict,
                    sem: asyncio.Semaphore) -> None:
    folder = SIM.LIBRARY_DIR / pid
    async with sem:
        log(key, "animating…")
        last = {"text": None}

        async def progress(text: str) -> None:
            if text != last["text"]:
                last["text"] = text
                log(key, text)

        out = await fal.animate(await upload(still), spec["motion"], negative=spec["negative"],
                                on_update=progress)
        raw = folder / "raw" / f"{key}.mp4"
        raw.write_bytes(await fal.download(out["url"]))
    web, poster = folder / f"{key}.mp4", folder / f"{key}.jpg"
    await asyncio.to_thread(video.transcode_clip, raw, web, width=960, crf=27)
    await asyncio.to_thread(video.poster, still, poster, width=960)
    man["places"][pid]["scenes"][key].update({
        "video": f"{pid}/{web.name}", "poster": f"{pid}/{poster.name}",
        "video_model": out["model"], "motion_prompt": spec["motion"],
        "negative_prompt": spec["negative"], "video_seconds": VIDEO_SECONDS,
        "video_bytes": web.stat().st_size, "generated_at": now()})
    SIM.save_manifest(man)
    log(key, f"clip ok ({out['elapsed_ms'] / 1000:.0f} s, {web.stat().st_size / 1e6:.2f} MB)")


async def estimate(stills: int, clips: int, model: str | None) -> None:
    models = [model or config.FAL_EDIT_MODEL, config.FAL_VIDEO_MODEL]
    prices = await fal.prices(models)
    print(f"To generate: {stills} still(s), {clips} clip(s) of {VIDEO_SECONDS} s.")
    img, vid = prices.get(models[0]), prices.get(models[1])
    if img and vid:
        per_clip = vid["unit_price"] * (VIDEO_SECONDS if "second" in vid["unit"] else 1)
        print(f"  Estimated list price: about {stills * img['unit_price'] + clips * per_clip:.2f} "
              f"{vid['currency']}")


async def main_async(args) -> int:
    pid = args.place
    if pid not in SIM.PLACES:
        print(f"Unknown place {pid!r}. Known: {', '.join(SIM.PLACES)}", file=sys.stderr)
        return 1
    place = SIM.PLACES[pid]
    folder = SIM.LIBRARY_DIR / pid
    for d in (folder, folder / "stills", folder / "raw"):
        d.mkdir(parents=True, exist_ok=True)
    if args.photo:
        for old in (folder / "raw").glob("photo.*"):
            old.unlink()
        shutil.copyfile(args.photo, folder / "raw" / f"photo{Path(args.photo).suffix.lower()}")
    photo = photo_path(folder)
    if not photo:
        print(f"No photo for {pid}: pass --photo <file> once.", file=sys.stderr)
        return 1

    print(f"Building the report for {place['query']}…")
    report = await R.build_report(query=place["query"], force_home=True)
    loc = report["location"]
    if SIM.place_at(loc["latitude"], loc["longitude"]) != pid:
        print(f"The address resolves to {loc['latitude']:.5f}, {loc['longitude']:.5f}, more than "
              f"{SIM.RADIUS_M} m from the place: fix its coordinates first.", file=sys.stderr)
        return 1
    tiles = view.risks(report)

    man = SIM.manifest()
    man = {"version": 1, **man, "places": dict(man.get("places", {}))}
    entry = man["places"].setdefault(pid, {})
    entry.update({"label": place["label"], "photo": f"{pid}/raw/{photo.name}",
                  "credit": place["credit"]})
    entry.setdefault("scenes", {})

    todo = []
    # The index is the tile's place among all four, so a risk keeps its seed with --only.
    for index, tile in enumerate(tiles):
        if args.only and tile["key"] not in args.only:
            continue
        spec = SIM.scene(report, tile)
        if not spec:
            log(tile["key"], "no level: skipped")
            continue
        rec = entry["scenes"].get(tile["key"], {})
        still = SIM.LIBRARY_DIR / rec["still"] if rec.get("still") else None
        fresh = rec.get("level") == tile["level"] and still is not None and still.is_file()
        todo.append({"index": index, "tile": tile, "spec": spec,
                     "still": still if fresh and not args.force else None,
                     "clip": bool(rec.get("video")) and fresh and not (args.force or args.redo_clips)})

    if args.dry_run:
        for t in todo:
            state = "ready" if t["clip"] else "still only" if t["still"] else "missing"
            print(f"\n[{state}] {t['tile']['key']} · {t['tile']['level']} ({t['tile']['score']}/100)"
                  f" · {t['spec']['what']}\n  image: {t['spec']['image']}\n  motion: {t['spec']['motion']}")
        print()
        await estimate(sum(1 for t in todo if not t["still"]),
                       sum(1 for t in todo if not t["clip"]), args.edit_model)
        return 0

    if not fal.available():
        print("FAL_KEY is not set: put it in .env first.", file=sys.stderr)
        return 1
    if not video.available():
        print("ffmpeg not found: pip install imageio-ffmpeg.", file=sys.stderr)
        return 1

    await estimate(sum(1 for t in todo if not t["still"]),
                   0 if args.stills_only else sum(1 for t in todo if not t["clip"]), args.edit_model)
    started = time.time()
    failures = []
    photo_url = None
    for t in todo:
        if t["still"]:
            continue
        key = t["tile"]["key"]
        try:
            photo_url = photo_url or await upload(photo)
            t["still"] = await make_still(pid, key, t["spec"], t["tile"], args.seed + t["index"],
                                          photo_url, man, args.edit_model)
            t["clip"] = False   # a new still makes the old clip stale
        except fal.FalUnavailable as exc:
            failures.append(key)
            log(key, f"[failed] {exc}")

    if not args.stills_only:
        sem = asyncio.Semaphore(args.parallel)

        async def one(t):
            try:
                await make_clip(pid, t["tile"]["key"], t["spec"], t["still"], man, sem)
            except (fal.FalUnavailable, video.VideoError) as exc:
                failures.append(t["tile"]["key"])
                log(t["tile"]["key"], f"[failed] {exc}")

        await asyncio.gather(*(one(t) for t in todo if t["still"] and not t["clip"]))

    print(f"\nDone in {time.time() - started:.0f} s.")
    if args.stills_only:
        print(f"Review the stills in {(folder / 'stills').relative_to(config.ROOT)}, regenerate "
              f"any with --only <risk> --force --stills-only, then run without --stills-only.")
    if failures:
        print(f"Failed: {', '.join(failures)}. Run it again: what is done is skipped.")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("place", nargs="?", default=next(iter(SIM.PLACES)),
                   help=f"place id (default: the first one): {', '.join(SIM.PLACES)}")
    p.add_argument("--photo", help="the street photo to draw on (kept in the place's raw/ folder)")
    p.add_argument("--only", nargs="*", choices=list(SIM.SCENES), help="risk keys")
    p.add_argument("--force", action="store_true", help="redraw the still and the clip")
    p.add_argument("--redo-clips", action="store_true", help="keep the stills, redo the clips")
    p.add_argument("--stills-only", action="store_true", help="stop before the (costlier) video")
    p.add_argument("--seed", type=int, default=SEED,
                   help="base seed (each risk adds its position): change it to redraw differently")
    p.add_argument("--edit-model", help=f"image edit model (default {config.FAL_EDIT_MODEL})")
    p.add_argument("--dry-run", action="store_true", help="list the prompts and estimate the cost")
    p.add_argument("--parallel", type=int, default=4, help="clips generated at the same time")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
