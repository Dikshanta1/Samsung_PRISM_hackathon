"""One-command generator for the official ten-direction clockwise sequence."""
from __future__ import annotations

from math import pi, sin, cos
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wrapper.blender_runner import blender_executable
from wrapper.eyes import Eyes
from wrapper.renderer import png_size

RENDERS = ROOT / "renders"
METADATA = ROOT / "metadata"
CONTACT_SHEET = ROOT / "outputs" / "contact_sheet.png"
DIRECTIONS = (
    "Top", "Upper-right", "Right-upper", "Right-lower", "Lower-right",
    "Bottom", "Lower-left", "Left-lower", "Left-upper", "Upper-left",
)


def sequence() -> list[tuple[int, float, float, float, str]]:
    """Return the official formula-derived frames without rounded computation."""
    return [(k, 2.0 * pi * k / 10.0, sin(2.0 * pi * k / 10.0), cos(2.0 * pi * k / 10.0), DIRECTIONS[k]) for k in range(10)]


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
    """Render all ten official frames and write generated, measured metadata."""
    RENDERS.mkdir(parents=True, exist_ok=True)
    METADATA.mkdir(parents=True, exist_ok=True)
    eyes = Eyes(RENDERS)
    records, paths, labels = [], [], []
    camera_matrix = None
    for frame, theta, h, v, direction in sequence():
        movement = eyes.move(h, v)
        path = eyes.render(f"frame_{frame:02d}.png")
        render = eyes.last_render
        if render is None or png_size(path) != (1024, 1024):
            raise RuntimeError(f"Frame {frame:02d} was not a valid 1024 x 1024 PNG")
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
            "image": str(path),
            "world_eye_rotations_quaternion": movement["world_eye_rotations_quaternion"],
            "world_eye_rotations_euler_xyz_degrees": render["eye_rotation_euler_xyz_degrees"],
            "pupil_center_2D": render["pupil_center_2D"],
            "camera_calibration": render["camera_calibration"],
            "camera_matrix": render["camera_matrix"],
            "angular_error_degrees": movement["angular_error_degrees"],
            "convergence": movement["convergence"],
        }
        (METADATA / f"frame_{frame:02d}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        records.append(record)
        paths.append(path)
        labels.append(f"{frame:02d}  {direction}")
        print(f"FRAME_OK {frame:02d} {direction} h={h:.16g} v={v:.16g} path={path}")
    contact = create_contact_sheet(paths, labels)
    manifest = METADATA / "official_sequence.json"
    manifest.write_text(json.dumps({"formula": "theta=2*pi*k/10; h=sin(theta); v=cos(theta)", "frames": records,
                                    "contact_sheet": str(contact)}, indent=2), encoding="utf-8")
    print(f"SEQUENCE_OK frames=10 manifest={manifest} contact_sheet={contact}")
    return manifest


if __name__ == "__main__":
    generate()
