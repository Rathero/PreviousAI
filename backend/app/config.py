"""Settings. Every value can be overridden with an environment variable or the `.env` file."""

from __future__ import annotations

import os
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parents[2]

# The project's .env is loaded before anything reads os.getenv.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # python-dotenv is optional: plain environment variables work too
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


VERSION = __version__
PRODUCT = "Previous AI"
USER_AGENT = f"PreviousAI/{VERSION} (natural hazard reports)"

DATA_DIR = Path(_env("DATA_DIR", str(ROOT / "data")))
CACHE_DIR = DATA_DIR / "cache"
CDS_DIR = DATA_DIR / "cds"
BASELINE_DIR = DATA_DIR / "baseline"
# Official Catalan layers, downloaded in batch by backend/scripts/catalonia_build.py.
CATALONIA_DIR = DATA_DIR / "catalonia"
# Generated media: the illustration library (backend/scripts/fal_media.py) and the
# narrated briefings, rendered on demand.
MEDIA_DIR = DATA_DIR / "media"
AUTONOMY_DIR = DATA_DIR / "autonomy"

for _d in (CACHE_DIR, CDS_DIR, BASELINE_DIR, CATALONIA_DIR, MEDIA_DIR, AUTONOMY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Time windows ---------------------------------------------------------------
# Start of the ERA5 record: 1979 is the satellite era, a good balance between a long
# series (reliable trends) and a light request.
ARCHIVE_START = _env("ERA5_ARCHIVE_START", "1979-01-01")
# ERA5 runs about five days behind real time.
ARCHIVE_LAG_DAYS = int(_env("ERA5_ARCHIVE_LAG_DAYS", "8"))
# The "current climate" window for the values shown.
CLIMATOLOGY_START = int(_env("CLIMATOLOGY_START", "1995"))

# Projections compare two windows of the SAME models, so the model bias cancels out.
PROJECTION_BASE = ("1995-01-01", "2014-12-31")
PROJECTION_FUTURE = ("2036-01-01", "2050-12-31")
CLIMATE_MODELS = _env("CLIMATE_MODELS", "EC_Earth3P_HR,MRI_AGCM3_2_S,MPI_ESM1_2_XR").split(",")

# --- Cache ------------------------------------------------------------------------
CACHE_TTL_SECONDS = int(_env("CACHE_TTL", str(30 * 24 * 3600)))
# If a source is unreachable, serve the last saved answer even if it has expired.
OFFLINE_FALLBACK = _env("OFFLINE_FALLBACK", "1") == "1"

# --- Copernicus Climate Data Store and Early Warning Data Store -------------------
CDS_URL = _env("CDS_URL", "https://cds.climate.copernicus.eu/api")
CDS_KEY = _env("CDS_API_KEY") or _env("CDSAPI_KEY")
EWDS_URL = _env("EWDS_URL", "https://ewds.climate.copernicus.eu/api")
EWDS_KEY = _env("EWDS_API_KEY")

# --- AI: typed decisions (reading requests, checking claims, ranking advice) ------
# Two interchangeable services answer the same typed questions (providers/ai.py).
# "nebius" or "typesafe" forces one; empty takes the first with a key, Nebius first.
# Without any key every feature falls back to deterministic code.
AI_PROVIDER = (_env("AI_PROVIDER", "") or "").lower()

NEBIUS_URL = _env("NEBIUS_URL", "https://api.tokenfactory.nebius.com/v1")
NEBIUS_KEY = _env("NEBIUS_API_KEY")
# Pinned: the confidence thresholds are checked against this model. It answers
# straight away (no reasoning tokens), which the log-probabilities need.
NEBIUS_MODEL = _env("NEBIUS_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507")

TYPESAFE_URL = _env("TYPESAFE_ENDPOINT", "https://api.typesafe.ai/v1/systemone")
TYPESAFE_KEY = _env("TYPESAFE_API_KEY")
# Pinned, not an alias that can move under us.
TYPESAFE_MODEL = _env("JEV_MODEL", "jev-1.13.0")

# --- fal.ai: generated media -------------------------------------------------------
# It illustrates numbers, narrates the briefing and transcribes voice; it never
# produces or changes a number.
FAL_KEY = _env("FAL_KEY")
# Pinned endpoints: the illustration manifest records exactly which model drew each clip.
FAL_IMAGE_MODEL = _env("FAL_IMAGE_MODEL", "fal-ai/nano-banana-2")
FAL_EDIT_MODEL = _env("FAL_EDIT_MODEL", "fal-ai/nano-banana-2/edit")
# For edits the default model will not make (a street under 2-3 m of water): slower,
# but it puts the waterline where the prompt says.
FAL_STRICT_EDIT_MODEL = _env("FAL_STRICT_EDIT_MODEL", "openai/gpt-image-2/edit")
FAL_VIDEO_MODEL = _env("FAL_VIDEO_MODEL", "fal-ai/kling-video/v2.5-turbo/pro/image-to-video")
# Eleven v3 rather than Turbo v2.5: slower, but the briefing is rendered in the
# background, and Turbo read it in a flat, robotic voice.
FAL_TTS_MODEL = _env("FAL_TTS_MODEL", "fal-ai/elevenlabs/tts/eleven-v3")
FAL_TTS_VOICE = _env("FAL_TTS_VOICE", "Brian")
# ElevenLabs Scribe v2: fast, and it can be biased towards place names, so local
# names come back spelt as the geocoders know them.
FAL_STT_MODEL = _env("FAL_STT_MODEL", "fal-ai/elevenlabs/speech-to-text/scribe-v2")
FAL_STT_KEYTERMS = [t.strip() for t in (_env(
    "FAL_STT_KEYTERMS",
    "Carrer,Calle,Avinguda,Avenida,Passeig,Paseo,Plaça,Plaza,Catalonia,Vielha,El Masnou,"
    "Val d'Aran,Girona,Barcelona",
) or "").split(",") if t.strip()]

# --- Google Street View ---------------------------------------------------------------
# Street View Static API. Without a key the home is shown from the air instead.
GOOGLE_MAPS_KEY = _env("GOOGLE_MAPS_API_KEY")

# --- Wildfire sources -------------------------------------------------------------------
FIRMS_KEY = _env("FIRMS_MAP_KEY")
FORECAST_PROVIDER = _env("FORECAST_PROVIDER", "ecmwf-aifs")

# --- Devin (autonomous engineering layer) --------------------------------------------
# Devin writes code on a branch; the gate (backend/autonomy/) decides whether it is
# admitted. Devin never produces or changes a number in a report.
DEVIN_API_URL = _env("DEVIN_API_URL", "https://api.devin.ai/v3")
DEVIN_API_KEY = _env("DEVIN_API_KEY")
DEVIN_ORG_ID = _env("DEVIN_ORG_ID")
DEVIN_REPO = _env("DEVIN_REPO", "Rathero/PreviousAI")

# --- Meteocat (official weather stations) --------------------------------------------
# Catalonia's open-data portal. Read through config so it can be redirected.
METEOCAT_URL = _env("METEOCAT_URL", "https://analisi.transparenciacatalunya.cat/resource")

HTTP_TIMEOUT = float(_env("HTTP_TIMEOUT", "45"))
# Sources that enrich a report without holding it up: if they are slow they are
# skipped with a warning.
SECONDARY_TIMEOUT = float(_env("SECONDARY_TIMEOUT", "20"))
