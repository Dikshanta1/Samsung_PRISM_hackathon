"""Generate official ground-truth records from fresh real Blender renders."""
from __future__ import annotations

from pathlib import Path
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.generate_official_sequence import generate as generate_sequence

METADATA_PATH = ROOT / "metadata.json"
SEQUENCE_MANIFEST = ROOT / "metadata" / "official_sequence.json"


def finite(value: object) -> None:
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"Non-finite numeric value: {value!r}")
    elif isinstance(value, list):
        for item in value:
            finite(item)
    elif isinstance(value, dict):
        for item in value.values():
            finite(item)


def generate() -> Path:
    """Re-render all ten frames and produce the official root ``metadata.json``."""
    generate_sequence()
    source = json.loads(SEQUENCE_MANIFEST.read_text(encoding="utf-8"))
    records = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    for measured, record in zip(source["frames"], records):
        # Provenance must be generated in Blender, not approximated in CPython.
        if "pupil_center_world_m" not in measured or "camera_calibration" not in measured:
            raise ValueError("Sequence manifest lacks actual 3D pupil or camera data")
        finite(record)
    if len(records) != 10:
        raise ValueError(f"Expected 10 measured frames, got {len(records)}")
    print(f"METADATA_GENERATION_OK records=10 path={METADATA_PATH}")
    return METADATA_PATH


if __name__ == "__main__":
    generate()
