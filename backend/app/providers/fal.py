"""fal.ai: generated media that illustrates, narrates and listens. Never numbers.

fal.ai is used for three things, and in none of them does it touch a figure:

  1. `media.py` + scripts/fal_media.py: a small library of illustration clips (a street
     with 30 cm of water, a heatwave afternoon...), generated ONCE in batch and kept in
     data/media. The report's data choose which clip a hazard shows; the clip never
     changes, adds or estimates a number.
  2. `briefing.py`: the voice of the narrated video briefing. The script is written by
     code from the report, word for word; the text-to-speech model only reads it.
  3. `/api/transcribe`: speech to text for the address box. The transcript lands in the
     box, where the person sees and can correct it before anything is analysed.

Calls go through the official `fal-client` package (queue submit, polling and the CDN
upload a recording needs). It is imported lazily: without it, or without FAL_KEY, the
API starts and every feature degrades.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import time
from typing import Awaitable, Callable

import httpx

from .. import config

PRICING_URL = "https://api.fal.ai/v1/models/pricing"
DOWNLOAD_TIMEOUT_S = 180.0
UPLOAD_RETRIES = 3
TTS_CACHE = config.CACHE_DIR / "fal_tts"


class FalUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(config.FAL_KEY)


def _client():
    if not available():
        raise FalUnavailable("FAL_KEY is not set")
    try:
        import fal_client
    except ImportError as exc:  # optional dependency
        raise FalUnavailable("the fal-client package is not installed "
                             "(pip install -r backend/requirements.txt)") from exc
    return fal_client, fal_client.AsyncClient(key=config.FAL_KEY)


async def run(model: str, arguments: dict, *, timeout: float = 600.0,
              on_update: Callable[[str], Awaitable[None] | None] | None = None) -> dict:
    """One queued call, waited for. Returns {"output", "model", "elapsed_ms"}.

    Raises FalUnavailable with a readable reason on any failure: callers fall back (a
    silent briefing, no voice button) instead of breaking the report.
    """
    fal_client, client = _client()
    started = time.perf_counter()

    async def update(status) -> None:
        if on_update is None:
            return
        name = type(status).__name__
        text = (f"queued (position {status.position})" if name == "Queued"
                else "generating" if name == "InProgress" else "done")
        maybe = on_update(text)
        if maybe is not None:
            await maybe

    try:
        output = await client.subscribe(model, arguments, client_timeout=timeout,
                                        on_queue_update=update, interval=1.0)
    except fal_client.FalClientHTTPError as exc:
        if exc.status_code in (401, 403):
            raise FalUnavailable(f"fal.ai rejected the key ({exc.status_code})") from exc
        raise FalUnavailable(f"fal.ai error {exc.status_code} on {model}: "
                             f"{str(exc.message)[:300]}") from exc
    except TimeoutError as exc:  # FalClientTimeoutError is a TimeoutError too
        raise FalUnavailable(f"fal.ai took more than {timeout:.0f} s on {model}") from exc
    except httpx.HTTPError as exc:
        raise FalUnavailable(f"fal.ai is not responding: {exc}") from exc
    return {"output": output, "model": model,
            "elapsed_ms": round((time.perf_counter() - started) * 1000)}


async def upload(data: bytes, content_type: str, file_name: str, *,
                 expires_in: str | None = None) -> str:
    """Puts bytes on fal's CDN and returns their URL (models take URLs, not files)."""
    fal_client, client = _client()
    lifecycle = fal_client.StorageSettings(expires_in=expires_in) if expires_in else None
    for attempt in range(UPLOAD_RETRIES):
        try:
            return await client.upload(data, content_type, file_name, lifecycle=lifecycle)
        except (fal_client.FalClientError, httpx.HTTPError) as exc:
            # The CDN answers the odd 503: a short back-off recovers it.
            if attempt == UPLOAD_RETRIES - 1:
                raise FalUnavailable(f"could not upload to fal.ai: {exc}") from exc
            await asyncio.sleep(1.5 * 2 ** attempt)


async def download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FalUnavailable(f"could not download the generated file: {exc}") from exc
        return resp.content


def _first_url(output: dict, *keys: str) -> str:
    """The generated file's URL, whatever shape the endpoint gives it."""
    for key in keys:
        value = output.get(key)
        if isinstance(value, list) and value:
            value = value[0]
        if isinstance(value, dict) and value.get("url"):
            return value["url"]
        if isinstance(value, str) and value.startswith("http"):
            return value
    raise FalUnavailable(f"unexpected fal.ai output: {json.dumps(output)[:200]}")


# --- Illustrations (batch only: scripts/fal_media.py) --------------------------------
async def image(prompt: str, *, seed: int | None = None, aspect_ratio: str = "16:9",
                on_update=None) -> dict:
    """Text to image. Returns {"url", "model", "elapsed_ms"}."""
    args = {"prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": "1K",
            "output_format": "jpeg", "num_images": 1}
    if seed is not None:
        args["seed"] = seed
    out = await run(config.FAL_IMAGE_MODEL, args, timeout=300, on_update=on_update)
    return {"url": _first_url(out["output"], "images", "image"), "model": out["model"],
            "elapsed_ms": out["elapsed_ms"]}


async def edit(image_url: str, prompt: str, *, seed: int | None = None, model: str | None = None,
               on_update=None) -> dict:
    """Image edit that keeps the scene (same street, more water)."""
    model = model or config.FAL_EDIT_MODEL
    if model.startswith("openai/"):
        args = {"prompt": prompt, "image_urls": [image_url], "image_size": "landscape_16_9",
                "quality": "high", "output_format": "jpeg", "num_images": 1}
    else:
        args = {"prompt": prompt, "image_urls": [image_url], "aspect_ratio": "auto",
                "resolution": "1K", "output_format": "jpeg", "num_images": 1}
        if seed is not None:
            args["seed"] = seed
    out = await run(model, args, timeout=600, on_update=on_update)
    return {"url": _first_url(out["output"], "images", "image"), "model": out["model"],
            "elapsed_ms": out["elapsed_ms"]}


async def animate(image_url: str, prompt: str, *, negative: str | None = None,
                  cfg_scale: float | None = None, on_update=None) -> dict:
    """Image to a 5-second clip. Returns {"url", "model", "elapsed_ms"}."""
    args = {"prompt": prompt, "image_url": image_url, "duration": "5",
            "cfg_scale": cfg_scale if cfg_scale is not None else 0.5}
    if negative:
        args["negative_prompt"] = negative
    out = await run(config.FAL_VIDEO_MODEL, args, timeout=900, on_update=on_update)
    return {"url": _first_url(out["output"], "video"), "model": out["model"],
            "elapsed_ms": out["elapsed_ms"]}


async def prices(endpoint_ids: list[str]) -> dict[str, dict]:
    """List prices per endpoint (unit_price, unit, currency). Best effort: {} on failure."""
    if not available():
        return {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(PRICING_URL, params={"endpoint_id": ",".join(endpoint_ids)},
                                    headers={"Authorization": f"Key {config.FAL_KEY}"})
            resp.raise_for_status()
            return {p["endpoint_id"]: p for p in resp.json().get("prices", [])}
    except (httpx.HTTPError, ValueError, KeyError):
        return {}


# --- Narration (briefing.py) ---------------------------------------------------------
def _tts_arguments(text: str, voice: str) -> dict:
    model = config.FAL_TTS_MODEL
    if "elevenlabs" in model:
        return {"text": text, "voice": voice, "stability": 0.6, "similarity_boost": 0.75,
                "speed": 1.08, "language_code": "en"}
    if "minimax" in model:
        return {"text": text, "voice_setting": {"voice_id": voice, "speed": 1.0}}
    return {"text": text}


def tts_path(text: str, voice: str):
    """Where a sentence read by this model and voice is kept."""
    args = _tts_arguments(text, voice)
    key = hashlib.sha256(json.dumps([config.FAL_TTS_MODEL, args], sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()[:24]
    return TTS_CACHE / f"{key}.mp3"


async def speak(text: str, *, voice: str | None = None) -> dict:
    """Reads a sentence written by code. Returns {"audio" (mp3 bytes), "model", "voice",
    "cached", "elapsed_ms"}. Cached on disk by (model, voice, text)."""
    voice = voice or config.FAL_TTS_VOICE
    args = _tts_arguments(text, voice)
    path = tts_path(text, voice)
    if path.exists() and path.stat().st_size > 0:
        return {"audio": path.read_bytes(), "model": config.FAL_TTS_MODEL, "voice": voice,
                "cached": True, "elapsed_ms": 0}
    out = await run(config.FAL_TTS_MODEL, args, timeout=120)
    audio = await download(_first_url(out["output"], "audio", "audio_url", "audio_file"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(audio)
    tmp.replace(path)
    return {"audio": audio, "model": out["model"], "voice": voice, "cached": False,
            "elapsed_ms": out["elapsed_ms"]}


# --- Voice input (/api/transcribe) -----------------------------------------------------
async def transcribe(audio: bytes, content_type: str, *, task: str = "transcribe") -> dict:
    """Speech to text. Returns {"text", "language", "model", "elapsed_ms"}.

    The recording goes to fal's CDN with a one-hour expiry, only so the model can read
    it; the app does not keep it and never caches transcripts.
    """
    base = (content_type or "audio/webm").split(";")[0].strip()
    ext = mimetypes.guess_extension(base) or ".webm"
    if base == "audio/webm":  # mimetypes has no entry for it on Windows
        ext = ".webm"
    url = await upload(audio, base, f"voice{ext}", expires_in="1h")
    model = config.FAL_STT_MODEL
    if task == "translate" or "whisper" in model or "wizper" in model:
        model = model if task != "translate" or "wizper" in model else "fal-ai/wizper"
        args = {"audio_url": url, "task": task, "language": None, "chunk_level": "segment"}
    else:  # ElevenLabs Scribe, biased towards street words and place names
        args = {"audio_url": url, "tag_audio_events": False, "diarize": False,
                "keyterms": config.FAL_STT_KEYTERMS[:100]}
    out = await run(model, args, timeout=90)
    result = out["output"]
    langs = result.get("languages") or [result.get("language_code")]
    return {"text": " ".join(str(result.get("text") or result.get("output") or "").split()),
            "language": langs[0] if langs else None,
            "model": out["model"], "elapsed_ms": out["elapsed_ms"]}
