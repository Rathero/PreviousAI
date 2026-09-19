"""Generates the illustration library with fal.ai (batch, once).

Each scene in `app/media.py` becomes a still (text to image, or an edit of the flood
street so all six water depths share one street) and then a 5-second clip (image to
video). The clips are re-encoded to a light web size and recorded in
data/media/illustrations/manifest.json with the models, prompts and seeds that drew them.
Reports only look clips up; nothing is generated on the user's path.

    python backend/scripts/fal_media.py --dry-run            # scenes, prompts, estimated cost
    python backend/scripts/fal_media.py --stills-only        # cheap: review the stills first
    python backend/scripts/fal_media.py                      # everything still missing
    python backend/scripts/fal_media.py --only flood-depth-3 heat-high --force
    python backend/scripts/fal_media.py --only wildfire-high --redo-clips   # same still, new clip
    python backend/scripts/fal_media.py --family flooding --new-base        # a different street

It is resumable: whatever is already in the manifest is skipped (unless --force), and the
manifest is saved after every scene. Needs FAL_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import config, media, video  # noqa: E402
from app.providers import fal  # noqa: E402

STILLS = media.LIBRARY_DIR / "stills"
RAW = media.LIBRARY_DIR / "raw"      # originals as fal delivered them (not versioned)
SEED = 20260919
VIDEO_SECONDS = 5


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(sid: str, text: str) -> None:
    print(f"  {sid:<22} {text}")


async def upload_still(path: Path) -> str:
    return await fal.upload(path.read_bytes(), "image/jpeg", path.name, expires_in="1d")


async def make_base(man: dict, force: bool) -> Path:
    """The flood street every depth band edits, so only the water changes."""
    base = media.FLOOD_BASE
    path = STILLS / f"{base['id']}.jpg"
    if path.exists() and not force:
        return path
    log(base["id"], "generating the base street…")
    out = await fal.image(base["prompt"], seed=SEED)
    path.write_bytes(await fal.download(out["url"]))
    man.setdefault("bases", {})[base["id"]] = {
        "still": f"stills/{path.name}", "image_model": out["model"], "image_prompt": base["prompt"],
        "seed": SEED, "generated_at": now()}
    media.save_manifest(man)
    log(base["id"], f"ok ({out['elapsed_ms'] / 1000:.0f} s)")
    return path


async def make_still(spec: dict, index: int, man: dict, force: bool, new_base: bool) -> Path:
    path = STILLS / f"{spec['id']}.jpg"
    rec = man["scenes"].get(spec["id"], {})
    if path.exists() and rec.get("still") and not force:
        return path
    seed = SEED + index
    if spec["base"]:
        base_path = await make_base(man, force=new_base)
        log(spec["id"], "editing the base street…")
        out = await fal.edit(await upload_still(base_path), spec["image_prompt"], seed=seed,
                             model=spec.get("edit_model"))
    else:
        log(spec["id"], "generating the still…")
        out = await fal.image(spec["image_prompt"], seed=seed)
    path.write_bytes(await fal.download(out["url"]))
    rec.update({"id": spec["id"], "still": f"stills/{path.name}", "image_model": out["model"],
                "image_prompt": spec["image_prompt"], "seed": seed, "base": spec["base"],
                "still_generated_at": now()})
    # A new still makes the old clip stale.
    for k in ("video", "poster", "video_model", "motion_prompt", "generated_at"):
        rec.pop(k, None)
    man["scenes"][spec["id"]] = rec
    media.save_manifest(man)
    log(spec["id"], f"still ok ({out['elapsed_ms'] / 1000:.0f} s) → {path.relative_to(config.ROOT)}")
    return path


async def make_clip(spec: dict, still: Path, man: dict, sem: asyncio.Semaphore) -> None:
    sid = spec["id"]
    async with sem:
        log(sid, "animating…")
        last = {"text": None}

        async def progress(text: str) -> None:
            if text != last["text"]:
                last["text"] = text
                log(sid, text)

        out = await fal.animate(await upload_still(still), spec["motion_prompt"],
                                negative=spec.get("negative") or media.VIDEO_NEGATIVE,
                                cfg_scale=spec.get("cfg_scale"), on_update=progress)
        raw = RAW / f"{sid}.mp4"
        raw.write_bytes(await fal.download(out["url"]))
    web = media.LIBRARY_DIR / f"{sid}.mp4"
    poster = media.LIBRARY_DIR / f"{sid}.jpg"
    await asyncio.to_thread(video.transcode_clip, raw, web, width=960, crf=27)
    await asyncio.to_thread(video.poster, still, poster, width=960)
    rec = man["scenes"][sid]
    rec.update({"video": web.name, "poster": poster.name, "video_model": out["model"],
                "motion_prompt": spec["motion_prompt"], "negative_prompt": spec.get("negative")
                or media.VIDEO_NEGATIVE, "video_seconds": VIDEO_SECONDS,
                "video_bytes": web.stat().st_size, "generated_at": now()})
    media.save_manifest(man)
    log(sid, f"clip ok ({out['elapsed_ms'] / 1000:.0f} s, {web.stat().st_size / 1e6:.2f} MB)")


def select(args) -> list[tuple[int, dict]]:
    scenes = list(enumerate(media.catalogue()))
    if args.only:
        scenes = [(i, s) for i, s in scenes if s["id"] in args.only]
    if args.family:
        scenes = [(i, s) for i, s in scenes if s["family"] == args.family]
    return scenes


async def estimate(scenes: list[tuple[int, dict]], man: dict, force: bool) -> None:
    stills = sum(1 for _, s in scenes if force or not man["scenes"].get(s["id"], {}).get("still"))
    clips = sum(1 for _, s in scenes if force or not media.generated(s["id"]))
    if any(s["base"] for _, s in scenes) and not (STILLS / f"{media.FLOOD_BASE['id']}.jpg").exists():
        stills += 1
    models = [config.FAL_IMAGE_MODEL, config.FAL_EDIT_MODEL, config.FAL_VIDEO_MODEL]
    prices = await fal.prices(models)
    print(f"To generate: {stills} still(s), {clips} clip(s) of {VIDEO_SECONDS} s.")
    for m in models:
        p = prices.get(m)
        print(f"  {m:<52} " + (f"{p['unit_price']} {p['currency']} per {p['unit']}" if p
                                 else "price unknown (needs FAL_KEY, or check fal.ai/pricing)"))
    img = prices.get(config.FAL_IMAGE_MODEL)
    vid = prices.get(config.FAL_VIDEO_MODEL)
    if img and vid:
        per_clip = vid["unit_price"] * (VIDEO_SECONDS if "second" in vid["unit"] else 1)
        total = stills * img["unit_price"] + clips * per_clip
        print(f"  Estimated list price: about {total:.2f} {vid['currency']}")


async def main_async(args) -> int:
    for d in (media.LIBRARY_DIR, STILLS, RAW):
        d.mkdir(parents=True, exist_ok=True)
    man = media.manifest()
    man = {"version": 1, **man, "scenes": dict(man.get("scenes", {}))}
    scenes = select(args)
    if not scenes:
        print("No scene matches.", file=sys.stderr)
        return 1

    if args.dry_run:
        for _, s in scenes:
            state = "ready" if media.generated(s["id"]) else (
                "still only" if man["scenes"].get(s["id"], {}).get("still") else "missing")
            print(f"\n[{state}] {s['id']} · {s['selector']}\n  image: {s['image_prompt']}"
                  f"\n  motion: {s['motion_prompt']}")
        print()
        await estimate(scenes, man, args.force)
        return 0

    if not fal.available():
        print("FAL_KEY is not set: put it in .env first.", file=sys.stderr)
        return 1
    if not video.available():
        print("ffmpeg not found: pip install imageio-ffmpeg.", file=sys.stderr)
        return 1

    await estimate(scenes, man, args.force)
    started = time.time()
    failures = []
    stills = {}
    base_pending = args.new_base  # one new street, shared by every depth band
    for index, spec in scenes:
        banded = bool(spec["base"])
        try:
            stills[spec["id"]] = await make_still(
                spec, index, man, args.force or (args.new_base and banded),
                base_pending and banded)
            base_pending = base_pending and not banded
        except fal.FalUnavailable as exc:
            failures.append(spec["id"])
            log(spec["id"], f"[failed] {exc}")
    if not args.stills_only:
        sem = asyncio.Semaphore(args.parallel)
        redo = args.force or args.redo_clips
        todo = [(s, stills[s["id"]]) for _, s in scenes
                if s["id"] in stills and (redo or not media.generated(s["id"]))]

        async def one(spec, still):
            try:
                await make_clip(spec, still, man, sem)
            except (fal.FalUnavailable, video.VideoError) as exc:
                failures.append(spec["id"])
                log(spec["id"], f"[failed] {exc}")

        await asyncio.gather(*(one(s, p) for s, p in todo))

    st = media.status()
    print(f"\nDone in {time.time() - started:.0f} s. Library: {st['generated']}/{st['scenes']} "
          f"clips ready.")
    if args.stills_only:
        print(f"Review the stills in {STILLS.relative_to(config.ROOT)}, regenerate any with "
              f"--only <id> --force --stills-only, then run without --stills-only.")
    if failures:
        print(f"Failed: {', '.join(failures)}. Run it again: what is done is skipped.")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", help="scene ids (see --dry-run)")
    p.add_argument("--family", choices=["flooding", "heat", "wildfire", "avalanche"])
    p.add_argument("--force", action="store_true", help="regenerate still and clip even if they exist")
    p.add_argument("--redo-clips", action="store_true", help="keep the stills, regenerate the clips")
    p.add_argument("--new-base", action="store_true",
                   help="regenerate the flood street (and so every depth band's still)")
    p.add_argument("--stills-only", action="store_true", help="stop before the (costlier) video")
    p.add_argument("--dry-run", action="store_true", help="list scenes and estimate the cost")
    p.add_argument("--parallel", type=int, default=3, help="clips generated at the same time")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
