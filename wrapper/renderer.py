"""Ordinary-Python renderer: one 1024 x 1024 PNG of the current eye pose.

    from wrapper.renderer import render
    path = render("renders/frame.png")

``render`` starts Blender in background mode on ``blender/scene.blend``, renders
whatever eye pose is saved there through the locked camera, and returns the
path of the PNG. The scene file is opened read-only: nothing is saved, so the
camera and lighting cannot be altered by rendering. Every failure is raised as
``RenderError`` with the reason and the tail of Blender's output.

Command line: ``python3 -m wrapper.renderer renders/frame.png``
"""
from __future__ import annotations

from pathlib import Path
import json
import struct
import subprocess
import sys

try:
    from .blender_runner import blender_executable
except ImportError:  # executed as a plain script rather than as a package module
    from blender_runner import blender_executable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = PROJECT_ROOT / "blender" / "scene.blend"
RENDER_SCRIPT = PROJECT_ROOT / "blender" / "render_frame.py"
EXPECTED_SIZE = (1024, 1024)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RESULT_PREFIX = "RENDER_RESULT "
ERROR_PREFIX = "RENDER_ERROR "
DEFAULT_TIMEOUT_S = 600.0


class RenderError(RuntimeError):
    """A render could not be produced or did not meet the output specification."""


def png_size(path: Path) -> tuple[int, int]:
    """Return ``(width, height)`` of a PNG, raising ``RenderError`` if it is not one."""
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or not header.startswith(PNG_SIGNATURE) or header[12:16] != b"IHDR":
        raise RenderError(f"{path} is not a valid PNG file")
    return struct.unpack(">II", header[16:24])


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def render_with_details(output_path: str | Path, *, scene: str | Path | None = None,
                        timeout: float = DEFAULT_TIMEOUT_S) -> tuple[Path, dict[str, object]]:
    """Render the current eye pose and also return Blender's report for the frame."""
    output = Path(output_path).expanduser().resolve()
    scene_path = Path(scene).expanduser().resolve() if scene else DEFAULT_SCENE
    if output.suffix.lower() != ".png":
        raise RenderError(f"Output path must end in .png, received {str(output_path)!r}")
    if not scene_path.is_file():
        raise RenderError(f"Scene file not found: {scene_path}")
    try:
        blender = blender_executable()
    except FileNotFoundError as error:
        raise RenderError(str(error)) from error
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()  # a stale image must never be mistaken for this render
    except OSError as error:
        raise RenderError(f"Cannot write to {output}: {error}") from error

    command = [str(blender), "--background", "--factory-startup", str(scene_path),
               "--python-exit-code", "1", "--python", str(RENDER_SCRIPT), "--", "--output", str(output)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RenderError(f"Blender did not finish rendering within {timeout:.0f} s") from error
    except OSError as error:
        raise RenderError(f"Could not start Blender at {blender}: {error}") from error

    log = completed.stdout + "\n" + completed.stderr
    reported_error = next((line[len(ERROR_PREFIX):] for line in log.splitlines() if line.startswith(ERROR_PREFIX)), None)
    if completed.returncode != 0 or reported_error:
        reason = reported_error or f"Blender exited with code {completed.returncode}"
        raise RenderError(f"Render failed: {reason}\n--- Blender output (tail) ---\n{_tail(log)}")
    result_line = next((line for line in log.splitlines() if line.startswith(RESULT_PREFIX)), None)
    if result_line is None:
        raise RenderError(f"Blender finished without reporting a render\n--- Blender output (tail) ---\n{_tail(log)}")
    if not output.is_file():
        raise RenderError(f"Blender reported success but {output} does not exist")
    size = png_size(output)
    if size != EXPECTED_SIZE:
        raise RenderError(f"{output} is {size[0]} x {size[1]} px, expected {EXPECTED_SIZE[0]} x {EXPECTED_SIZE[1]}")
    return output, json.loads(result_line[len(RESULT_PREFIX):])


def render(output_path: str | Path, *, scene: str | Path | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> Path:
    """Render the current eye position to a 1024 x 1024 PNG and return its path."""
    return render_with_details(output_path, scene=scene, timeout=timeout)[0]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 -m wrapper.renderer OUTPUT.png")
    try:
        print(render(sys.argv[1]))
    except RenderError as error:
        raise SystemExit(f"RenderError: {error}")


if __name__ == "__main__":
    main()
