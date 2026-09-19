"""The tasks the autonomous layer can hand to Devin, each with its own gate."""

from . import station_witness

TASKS = {station_witness.ID: station_witness}
