"""Ordinary-Python orchestration for invoking Blender reproducibly."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

DEFAULT_MACOS_BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")


def blender_executable() -> Path:
    configured = os.environ.get("BLENDER_BIN")
    candidates = [Path(configured)] if configured else []
    discovered = shutil.which("blender")
    if discovered:
        candidates.append(Path(discovered))
    candidates.append(DEFAULT_MACOS_BLENDER)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(
        "Blender executable not found. Set BLENDER_BIN or install Blender in /Applications."
    )


def run_background(script: Path, *script_arguments: str) -> subprocess.CompletedProcess[str]:
    command = [str(blender_executable()), "--background", "--python", str(script), "--", *script_arguments]
    return subprocess.run(command, check=True, text=True, capture_output=True)


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    destination = project_root / "renders" / "smoke_test.png"
    result = run_background(project_root / "blender" / "smoke_scene.py", str(destination))
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")


if __name__ == "__main__":
    main()
