"""ffmpeg, for the few video jobs done locally.

Re-encoding generated clips to a light web size, extracting posters and assembling the
narrated briefing. ffmpeg comes from, in order: FFMPEG_PATH, the PATH, or the binary
bundled with the `imageio-ffmpeg` package (so nothing has to be installed by hand).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path


class VideoError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str | None:
    explicit = os.getenv("FFMPEG_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def available() -> bool:
    return ffmpeg_exe() is not None


def run(args: list[str], *, timeout: float = 300) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise VideoError("ffmpeg not found: pip install imageio-ffmpeg, or set FFMPEG_PATH")
    proc = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise VideoError(f"ffmpeg failed: {proc.stderr.strip()[-600:]}")


async def arun(args: list[str], *, timeout: float = 300) -> None:
    """The same, off the event loop: encoding must not freeze the API."""
    await asyncio.to_thread(run, args, timeout=timeout)


def transcode_clip(src: Path, dst: Path, *, width: int = 960, crf: int = 27,
                   seconds: float | None = None) -> None:
    """H.264 for the web: even size, no audio, moov atom first so it starts playing
    before it has downloaded."""
    args = ["-i", str(src)]
    if seconds:
        args += ["-t", f"{seconds:.2f}"]
    args += ["-an", "-vf", f"scale={width}:-2:flags=lanczos,fps=24,format=yuv420p",
             "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-profile:v", "high",
             "-movflags", "+faststart", str(dst)]
    run(args)


def poster(src: Path, dst: Path, *, width: int = 960, at: float = 0.0, quality: int = 4) -> None:
    """A JPEG frame of a clip (or a resized image): what shows before it plays."""
    args = []
    if at:
        args += ["-ss", f"{at:.2f}"]
    args += ["-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2:flags=lanczos",
             "-q:v", str(quality), str(dst)]
    run(args)


def to_wav(src: Path, dst: Path) -> float:
    """Any audio to 44.1 kHz mono WAV; returns its duration in seconds."""
    run(["-i", str(src), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(dst)])
    return wav_seconds(dst)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())
