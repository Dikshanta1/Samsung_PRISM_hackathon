"""One-command generator for the official ten-direction clockwise sequence.

    python3 scripts/generate_official_sequence.py

For k = 0..9: theta = 2*pi*k/10, h = sin(theta), v = cos(theta), starting at the
top and going clockwise in the image. Each frame is posed and rendered in the
real Blender scene through ``wrapper.eyes.Eyes``; nothing is typed in by hand
and no earlier image is reused. The command writes

    renders/frame_00.png ... renders/frame_09.png
    metadata.json                      (official format, one record per render)
    metadata/frame_00.json ... frame_09.json, metadata/official_sequence.json
    outputs/contact_sheet.png

and then checks them with ``tests/test_official_sequence.py``.
"""
from __future__ import annotations

from math import pi, sin, cos
from pathlib import Path
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from wrapper.blender_runner import blender_executable
from wrapper.eyes import Eyes
from wrapper.renderer import png_size

RENDERS = ROOT / "renders"
METADATA = ROOT / "metadata"
CONTACT_SHEET = ROOT / "outputs" / "contact_sheet.png"
MANIFEST = METADATA / "official_sequence.json"
OFFICIAL_METADATA = ROOT / "metadata.json"
FRAME_COUNT = 10
DIRECTIONS = (
    "Top", "Upper-right", "Right-upper", "Right-lower", "Lower-right",
    "Bottom", "Lower-left", "Left-lower", "Left-upper", "Upper-left",
)


def sequence() -> list[tuple[int, float, float, float, str]]:
    """Return ``(k, theta, h, v, direction)`` for the ten frames, at full double precision."""
    return [(k, 2.0 * pi * k / 10.0, sin(2.0 * pi * k / 10.0), cos(2.0 * pi * k / 10.0), DIRECTIONS[k])
            for k in range(FRAME_COUNT)]


def remove_previous_outputs() -> None:
    """Delete every earlier frame, record and sheet so none can be mistaken for this run's."""
    stale = [*RENDERS.glob("frame_*.png"), *METADATA.glob("frame_*.json"), MANIFEST, OFFICIAL_METADATA, CONTACT_SHEET]
    for path in stale:
        path.unlink(missing_ok=True)


def official_record(record: dict) -> dict:
    """One render in the official ``metadata.json`` layout, with exactly its eight keys.

    Rotations are world-frame XYZ Euler angles in degrees; pupil centres are
    pixels (origin top-left, y down); the camera matrix is the 3 x 4 P = K [R | t].
    """
    return {
        "frame": record["frame"],
        "theta": record["theta_radians"],
        "input": {"h": record["inputs"]["h"], "v": record["inputs"]["v"]},
        "eye_rotation_L": record["world_eye_rotations_euler_xyz_degrees"]["L"],
        "eye_rotation_R": record["world_eye_rotations_euler_xyz_degrees"]["R"],
        "pupil_center_2D_L": record["pupil_center_2D"]["L"],
        "pupil_center_2D_R": record["pupil_center_2D"]["R"],
        "camera_matrix": record["camera_matrix"],
    }


def create_contact_sheet(frames: list[Path], labels: list[str]) -> Path:
    command = [str(blender_executable()), "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", str(ROOT / "scripts" / "contact_sheet.py"), "--", "--output", str(CONTACT_SHEET)]
    for frame, label in zip(frames, labels):
        command.extend(("--frame", str(frame), "--label", label))
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Contact sheet generation failed:\n" + result.stdout + result.stderr)
    if not CONTACT_SHEET.is_file() or CONTACT_SHEET.stat().st_size == 0:
        raise RuntimeError("Contact sheet command completed without output")
    return CONTACT_SHEET


def generate() -> Path:
    """Render all ten official frames, write measured metadata, and verify the result."""
    started = time.time()
    RENDERS.mkdir(parents=True, exist_ok=True)
    METADATA.mkdir(parents=True, exist_ok=True)
    remove_previous_outputs()
    eyes = Eyes(RENDERS)
    records, paths, labels = [], [], []
    camera_matrix = None
    for frame, theta, h, v, direction in sequence():
        movement = eyes.move(h, v)
        path = eyes.render(f"frame_{frame:02d}.png")
        render = eyes.last_render
        if render is None or png_size(path) != (1024, 1024):
            raise RuntimeError(f"Frame {frame:02d} was not a valid 1024 x 1024 PNG")
        if render["inputs"] != {"h": h, "v": v}:
            raise RuntimeError(f"Frame {frame:02d} was rendered with {render['inputs']}, not h={h!r}, v={v!r}")
        if not render["camera_fixed"] or not render["lighting_constant"]:
            raise RuntimeError(f"Frame {frame:02d} did not preserve camera or lighting")
        if camera_matrix is None:
            camera_matrix = render["camera_matrix"]
        elif render["camera_matrix"] != camera_matrix:
            raise RuntimeError(f"Camera matrix changed at frame {frame:02d}")
        record = {
            "frame": frame,
            "direction": direction,
            "theta_radians": theta,
            "inputs": {"h": h, "v": v},
            "image": path.relative_to(ROOT).as_posix(),
            # Everything below was measured by Blender in the process that rendered this image.
            "world_eye_rotations_quaternion": render["world_eye_rotations_quaternion"],
            "world_eye_rotations_euler_xyz_degrees": render["eye_rotation_euler_xyz_degrees"],
            "world_eye_rotations_euler_xyz_radians": render["eye_rotation_euler_xyz_radians"],
            "pupil_center_2D": render["pupil_center_2D"],
            "pupil_center_world_m": render["pupil_center_world_m"],
            "camera_calibration": render["camera_calibration"],
            "camera_matrix": render["camera_matrix"],
            "angular_error_degrees": render["angular_error_degrees"],
            "convergence": render["convergence"],
        }
        if movement["pupil_center_2D"] != render["pupil_center_2D"]:
            raise RuntimeError(f"Frame {frame:02d}: the rendered pose differs from the pose set by move()")
        (METADATA / f"frame_{frame:02d}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        records.append(record)
        paths.append(path)
        labels.append(f"{frame:02d}  {direction} | h = {h:+.3f}   v = {v:+.3f}")
        print(f"FRAME_OK {frame:02d} {direction} h={h:.17g} v={v:.17g} path={path}", flush=True)
    contact = create_contact_sheet(paths, labels)
    MANIFEST.write_text(json.dumps({"formula": "theta=2*pi*k/10; h=sin(theta); v=cos(theta)", "frames": records,
                                    "contact_sheet": contact.relative_to(ROOT).as_posix()}, indent=2), encoding="utf-8")
    OFFICIAL_METADATA.write_text(json.dumps([official_record(record) for record in records], indent=2), encoding="utf-8")
    print(f"SEQUENCE_OK frames={FRAME_COUNT} metadata={OFFICIAL_METADATA} manifest={MANIFEST} contact_sheet={contact}", flush=True)

    from test_official_sequence import verify
    verify(generated_after=started)
    return MANIFEST


if __name__ == "__main__":
    generate()
