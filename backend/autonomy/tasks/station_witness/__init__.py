"""Task `station-witness`: Meteocat's stations as an independent witness for heat.

Why this task (see SPEC.md): every heat number in a Catalan report comes from one model,
ERA5, and the only cross-check compares ERA5 with ERA5. The trigger is the report itself
(`app/evidence.py`): a number resting on one source.
"""

from pathlib import Path

from . import checks

ID = "station-witness"
TITLE = "Bring the thermometer: Meteocat stations as an independent witness for the heat numbers"
SPEC = Path(__file__).with_name("SPEC.md")
ALLOWED = checks.ALLOWED
CHECKS = checks.CHECKS
Context = checks.Context
