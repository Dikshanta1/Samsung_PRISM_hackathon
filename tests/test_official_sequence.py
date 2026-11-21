"""Acceptance check of the generated official ten-direction sequence.

    python3 tests/test_official_sequence.py

Checks the files written by ``scripts/generate_official_sequence.py`` (which
also runs this check itself). Ordinary Python; the images are decoded with the
standard library and the gaze is measured from their pixels: each frame's
pupil-mask render gives where the renderer drew each pupil, and the photoreal
frame must show a dark pupil at that point.
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, pi, radians, sin
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from metadata.pupil_pixels import MASK_BAND_ROWS, mask_centroids, pupil_contrast_problem
from test_wrapper import FOREHEAD, assert_same_region, read_png_rows, region
from wrapper.renderer import png_size

RENDERS = ROOT / "renders"
METADATA = ROOT / "metadata"
CONTACT_SHEET = ROOT / "outputs" / "contact_sheet.png"
PUPIL_MASKS = ROOT / "outputs" / "pupil_masks"
OFFICIAL_METADATA = ROOT / "metadata.json"
OFFICIAL_KEYS = ["frame", "theta", "input", "eye_rotation_L", "eye_rotation_R",
                 "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix"]
DIRECTIONS = ("Top", "Upper-right", "Right-upper", "Right-lower", "Lower-right",
              "Bottom", "Lower-left", "Left-lower", "Left-upper", "Upper-left")
MIN_RADIUS_PX = 10.0  # every frame is a full-range move; the pupil travels about 12 px
MAX_DIRECTION_ERROR_DEGREES = 3.0  # mask centroids are exact to a few hundredths of a pixel
PIXEL_TOLERANCE_PX = 0.25
POSE_MEASURED_KEYS = ("reference_point_world_m", "camera_distance_m")


def verify(generated_after: float | None = None) -> None:
    frames = sorted(RENDERS.glob("frame_*.png"))
    assert [path.name for path in frames] == [f"frame_{k:02d}.png" for k in range(10)], \
        f"Expected exactly frame_00..frame_09, found {[path.name for path in frames]}"
    manifest = json.loads((METADATA / "official_sequence.json").read_text(encoding="utf-8"))
    records = manifest["frames"]
    assert len(records) == 10, f"Manifest holds {len(records)} frames"

    official = json.loads(OFFICIAL_METADATA.read_text(encoding="utf-8"))
    assert isinstance(official, list) and len(official) == 10, "metadata.json must hold one record per render"
    if generated_after is not None:
        assert OFFICIAL_METADATA.stat().st_mtime >= generated_after, "metadata.json is older than this run"

    last_row = 640
    pixels, measured = [], []
    for k, (path, record) in enumerate(zip(frames, records)):
        theta = 2.0 * pi * k / 10.0
        # Exact formula, bit for bit, and the stated direction.
        assert record["frame"] == k and record["direction"] == DIRECTIONS[k]
        assert record["theta_radians"] == theta, f"frame {k}: theta {record['theta_radians']!r}"
        assert record["inputs"] == {"h": sin(theta), "v": cos(theta)}, f"frame {k}: inputs {record['inputs']}"
        assert record["image"] == f"renders/{path.name}"
        assert json.loads((METADATA / f"frame_{k:02d}.json").read_text(encoding="utf-8")) == record
        if generated_after is not None:
            assert path.stat().st_mtime >= generated_after, f"{path.name} is older than this run"
        # The official record has exactly the specified keys and the same measured values.
        entry = official[k]
        assert list(entry) == OFFICIAL_KEYS, f"metadata.json frame {k}: keys are {list(entry)}"
        assert entry["frame"] == k and entry["theta"] == theta
        assert entry["input"] == {"h": sin(theta), "v": cos(theta)}
        for side in ("L", "R"):
            rotation = entry[f"eye_rotation_{side}"]
            assert rotation == record["world_eye_rotations_euler_xyz_degrees"][side] and len(rotation) == 3
            assert entry[f"pupil_center_2D_{side}"] == record["pupil_center_2D"][side]
            # Cross-check against the independently recorded quaternion: both must give the same gaze.
            w, x, y, z = record["world_eye_rotations_quaternion"][side]
            from_quaternion = (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x))  # R @ +Y
            rx, ry, rz = (radians(angle) for angle in rotation)
            cx, sx, cy, sy, cz, sz = cos(rx), sin(rx), cos(ry), sin(ry), cos(rz), sin(rz)
            from_euler = (cz * sy * sx - sz * cx, sz * sy * sx + cz * cx, cy * sx)  # (Rz Ry Rx) @ +Y
            assert max(abs(a - b) for a, b in zip(from_quaternion, from_euler)) < 1e-5, \
                f"frame {k} {side}: eye_rotation does not match the recorded quaternion"
        assert entry["camera_matrix"] == record["camera_matrix"] == official[0]["camera_matrix"]
        assert len(entry["camera_matrix"]) == 3 and all(len(row) == 4 for row in entry["camera_matrix"])
        # Valid 1024 x 1024 8-bit RGB PNG (every chunk CRC and the whole pixel stream are checked).
        assert png_size(path) == (1024, 1024)
        rows = read_png_rows(path, last_row)
        pixels.append(rows)
        # Fixed camera: identical projection matrix, and pixels away from the eyes do not change.
        assert record["camera_matrix"] == records[0]["camera_matrix"], f"frame {k}: camera matrix changed"
        calibration, first = record["camera_calibration"], records[0]["camera_calibration"]
        for key, value in calibration.items():
            if key in POSE_MEASURED_KEYS:  # read from the posed eyeballs: equal to float32 rounding only
                values = value if isinstance(value, list) else [value]
                firsts = first[key] if isinstance(first[key], list) else [first[key]]
                assert max(abs(x - y) for x, y in zip(values, firsts)) < 1e-6, f"frame {k}: {key} changed"
            else:
                assert value == first[key], f"frame {k}: camera {key} changed"
        assert abs(calibration["camera_distance_m"] - 0.400) < 1e-6, f"frame {k}: camera is not 0.400 m away"
        assert_same_region(region(rows, FOREHEAD), region(pixels[0], FOREHEAD), f"frame {k}: the forehead changed")
        assert max(record["angular_error_degrees"].values()) < 0.001, f"frame {k}: eyes are off target"
        # The pupil the renderer drew (mask render of the same pose and camera) is where the
        # metadata says it is, and the photoreal frame shows a dark pupil at that point.
        mask = PUPIL_MASKS / f"frame_{k:02d}.png"
        assert record["pupil_mask"]["image"] == f"outputs/pupil_masks/{mask.name}" and png_size(mask) == (1024, 1024)
        found = mask_centroids(read_png_rows(mask, MASK_BAND_ROWS[1]))
        for side in ("L", "R"):
            reported = record["pupil_center_2D"][side]
            error = max(abs(found[side][0] - reported[0]), abs(found[side][1] - reported[1]))
            assert error <= PIXEL_TOLERANCE_PX, f"frame {k} {side}: rendered pupil is {error:.3f} px from the metadata"
            problem = pupil_contrast_problem(rows, reported)
            assert problem is None, f"frame {k} {side}: pupil_center_2D {problem}"
        measured.append(found)
    assert len({bytes(b"".join(rows)) for rows in pixels}) == 10, "Two frames are the same image"

    # Actual gaze movement: around each eye's mean position the rendered pupil sits
    # at clock angle theta (0 = top, increasing clockwise in the image). Each frame
    # being within 8 degrees of 36k degrees also fixes the order: clockwise from the top.
    report = []
    for side in ("L", "R"):
        mean_u = sum(frame[side][0] for frame in measured) / 10
        mean_v = sum(frame[side][1] for frame in measured) / 10
        for k, frame in enumerate(measured):
            du, dv = frame[side][0] - mean_u, frame[side][1] - mean_v
            radius = hypot(du, dv)
            angle = degrees(atan2(du, -dv)) % 360.0
            error = (angle - 36.0 * k + 180.0) % 360.0 - 180.0
            assert radius >= MIN_RADIUS_PX, f"frame {k} {side}: pupil moved only {radius:.1f} px"
            assert abs(error) <= MAX_DIRECTION_ERROR_DEGREES, \
                f"frame {k} {side}: pupil is at {angle:.1f} deg, expected {36 * k} deg"
            if side == "L":
                report.append(f"{k}:{angle:.0f}deg/{radius:.1f}px")

    width, height = png_size(CONTACT_SHEET)
    assert width >= 5 * 512 and height >= 2 * 512, f"Contact sheet is only {width} x {height}"
    if generated_after is not None:
        assert CONTACT_SHEET.stat().st_mtime >= generated_after, "The contact sheet is older than this run"
    print("GAZE_MEASURED_L " + " ".join(report))
    print(f"OFFICIAL_SEQUENCE_OK frames=10 size=1024x1024 formula=exact clockwise=true camera_fixed=true metadata_json=10 "
          f"contact_sheet={width}x{height}")


if __name__ == "__main__":
    verify()
