"""Build the official ``metadata.json`` from measurements taken in Blender.

    python3 metadata/metadata_generator.py

``generate()`` renders the ten official frames with the real scene (through
``scripts/generate_official_sequence.py``) and writes one record per render:

    {"frame", "theta", "input": {"h", "v"},
     "eye_rotation_L", "eye_rotation_R",        [rx, ry, rz]
     "pupil_center_2D_L", "pupil_center_2D_R",  [x, y]
     "camera_matrix"}                           3 x 4

Nothing here is typed in. For each frame, ``scripts/blender_worker.py`` reads,
in the Blender process that renders the image:

* eye rotations: ``Eye_L`` / ``Eye_R`` ``matrix_world.to_euler("XYZ")``;
* 3D pupil centres: the mean of the open-margin vertices of ``Pupil_L`` /
  ``Pupil_R``, transformed to world space;
* 2D pupil centres: those points projected through the scene camera;
* camera matrix: ``P = K [R | t]`` derived from the scene camera.

Conventions: rotations are world-frame Euler angles in XYZ order (R = Rz Ry Rx,
i.e. rotate about world X, then Y, then Z), in degrees. Pixels have their
origin at the top-left corner, x right, y down. Lengths are metres.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

METADATA_PATH = ROOT / "metadata.json"
EULER_ORDER = "XYZ"
ROTATION_UNIT = "degrees"
REQUIRED_KEYS = ("frame", "theta", "input", "eye_rotation_L", "eye_rotation_R",
                 "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix")


def _numbers(value: object, where: str, shape: tuple[int, ...]) -> list:
    """Return ``value`` as nested lists of finite floats with exactly ``shape``."""
    if not shape:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where} is not a number: {value!r}")
        if not math.isfinite(value):
            raise ValueError(f"{where} is not finite: {value!r}")
        return float(value)  # type: ignore[return-value]
    if not isinstance(value, (list, tuple)) or len(value) != shape[0]:
        raise ValueError(f"{where} must have {shape[0]} entries, received {value!r}")
    return [_numbers(item, f"{where}[{index}]", shape[1:]) for index, item in enumerate(value)]


def official_record(measured: dict) -> dict:
    """Convert one frame's Blender measurements into an official record.

    Raises ``ValueError`` if a measurement is missing, has the wrong shape, or
    is NaN or infinite.
    """
    frame = measured.get("frame")
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise ValueError(f"frame must be an integer, received {frame!r}")
    where = f"frame {frame}"
    try:
        rotations = measured[f"world_eye_rotations_euler_{EULER_ORDER.lower()}_{ROTATION_UNIT}"]
        return {
            "frame": frame,
            "theta": _numbers(measured["theta_radians"], f"{where} theta", ()),
            "input": {"h": _numbers(measured["inputs"]["h"], f"{where} h", ()),
                      "v": _numbers(measured["inputs"]["v"], f"{where} v", ())},
            "eye_rotation_L": _numbers(rotations["L"], f"{where} eye_rotation_L", (3,)),
            "eye_rotation_R": _numbers(rotations["R"], f"{where} eye_rotation_R", (3,)),
            "pupil_center_2D_L": _numbers(measured["pupil_center_2D"]["L"], f"{where} pupil_center_2D_L", (2,)),
            "pupil_center_2D_R": _numbers(measured["pupil_center_2D"]["R"], f"{where} pupil_center_2D_R", (2,)),
            "camera_matrix": _numbers(measured["camera_matrix"], f"{where} camera_matrix", (3, 4)),
        }
    except (KeyError, TypeError) as error:
        raise ValueError(f"{where}: Blender measurement {error} is missing") from error


def build_metadata(measured_frames: list[dict]) -> list[dict]:
    """Official records for the measured frames, which must be numbered 0, 1, 2, ..."""
    records = [official_record(measured) for measured in measured_frames]
    numbering = [record["frame"] for record in records]
    if numbering != list(range(len(records))):
        raise ValueError(f"Frames must be numbered consecutively from 0, received {numbering}")
    return records


def write_metadata(measured_frames: list[dict], path: Path = METADATA_PATH) -> Path:
    """Write the official metadata file; NaN and infinity can never be written."""
    records = build_metadata(measured_frames)
    path.write_text(json.dumps(records, indent=2, allow_nan=False), encoding="utf-8")
    return path


def generate() -> Path:
    """Render all ten frames afresh and write the official root ``metadata.json``."""
    from scripts.generate_official_sequence import generate as generate_sequence
    generate_sequence()  # poses, renders and measures in Blender, then calls write_metadata()
    records = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    if len(records) != 10:
        raise ValueError(f"Expected 10 records, found {len(records)}")
    print(f"METADATA_GENERATION_OK records=10 path={METADATA_PATH}")
    return METADATA_PATH


if __name__ == "__main__":
    generate()
