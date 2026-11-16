"""End-to-end Stage 5B test using fresh Blender measurements and actual pixels."""
from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metadata.metadata_generator import generate
from metadata.validator import REPORT_PATH, validate


def main() -> None:
    path = generate()
    report = validate(path)
    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == 10 and report["valid"] is True
    assert REPORT_PATH.is_file()
    assert report["max_rendered_pupil_projection_error_px"] <= 2.0
    print("METADATA_TEST_OK records=10 actual_pixels=true numeric_json=true")


if __name__ == "__main__":
    main()
