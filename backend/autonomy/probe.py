"""Runs Devin's code in its own checkout, in a separate process.

The gate never imports the code it judges: a driver script (from this tree,
`autonomy/drivers/`) is started with the checkout's `backend` first on the path, does
one job and writes JSON. A crash, a hang or a stray `sys.exit` stays in the subprocess
and comes back as evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DRIVERS = Path(__file__).resolve().parent / "drivers"
_KEEP = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA",
         "LOCALAPPDATA", "COMSPEC", "PATHEXT", "WINDIR", "LANG")


def clean_env(extra: dict | None = None) -> dict:
    """A minimal environment: no API keys from this shell reach Devin's code, except the
    data directory, which by default is the product's own (the local data cache)."""
    from app import config  # this tree

    env = {k: v for k, v in os.environ.items() if k.upper() in _KEEP}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "DATA_DIR": str(config.DATA_DIR)})
    env.update(extra or {})
    return env


def run_driver(tree: Path, driver: str, args: dict, *, env: dict | None = None,
               timeout: int = 600) -> dict:
    with tempfile.TemporaryDirectory(prefix="pai-probe-") as tmp:
        out = Path(tmp) / "out.json"
        full_env = clean_env(env)
        full_env["TARGET_BACKEND"] = str(Path(tree) / "backend")
        try:
            proc = subprocess.run([sys.executable, str(DRIVERS / driver), json.dumps(args), str(out)],
                                  cwd=tree, env=full_env, capture_output=True, text=True,
                                  timeout=timeout, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return {"error": f"{driver} did not finish within {timeout} s"}
        if out.exists():
            try:
                return json.loads(out.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return {"error": f"{driver} wrote unreadable output: {exc}"}
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        return {"error": f"{driver} exited with {proc.returncode}: " + " | ".join(tail)}
