"""Simple external API for the Samsung PRISM binocular-eye Blender scene."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
from typing import Any

from .blender_runner import blender_executable
from .renderer import RenderError, render

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "blender_worker.py"
RESULT_PREFIX = "WORKER_RESULT "
ERROR_PREFIX = "WORKER_ERROR "


class BlenderWorkerError(RuntimeError):
    """Blender could not load or control the real eye scene."""


class Eyes:
    """Control the saved Blender scene through background Blender processes.

    The class is safe to import from ordinary system Python.  It never imports
    ``bpy``; every scene mutation is delegated to ``scripts/blender_worker.py``
    inside Blender's bundled Python runtime.
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        *,
        scene: str | Path | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.scene = Path(scene).expanduser().resolve() if scene else ROOT / "blender" / "scene.blend"
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else ROOT / "outputs"
        self.timeout = timeout
        self._render_index = 0
        if not self.scene.is_file():
            raise FileNotFoundError(f"Blender scene not found: {self.scene}")

    @staticmethod
    def _validate(h: float, v: float) -> None:
        if not (-1.0 <= h <= 1.0 and -1.0 <= v <= 1.0):
            raise ValueError(f"h and v must be in [-1, +1], received h={h}, v={v}")

    @staticmethod
    def _tail(text: str, limit: int = 20) -> str:
        return "\n".join(text.strip().splitlines()[-limit:])

    def _run(self, action: str, h: float = 0.0, v: float = 0.0) -> dict[str, Any]:
        command = [
            str(blender_executable()), "--background", str(self.scene), "--python-exit-code", "1",
            "--python", str(WORKER), "--", action, "--h", str(h), "--v", str(v), "--save",
        ]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise BlenderWorkerError(f"Blender {action} timed out after {self.timeout:.0f} s") from error
        except OSError as error:
            raise BlenderWorkerError(f"Could not launch Blender for {action}: {error}") from error
        log = result.stdout + "\n" + result.stderr
        worker_error = next((line[len(ERROR_PREFIX):] for line in log.splitlines() if line.startswith(ERROR_PREFIX)), None)
        if result.returncode or worker_error:
            reason = worker_error or f"Blender exited with code {result.returncode}"
            raise BlenderWorkerError(f"{action} failed: {reason}\n--- Blender output (tail) ---\n{self._tail(log)}")
        line = next((line for line in log.splitlines() if line.startswith(RESULT_PREFIX)), None)
        if line is None:
            raise BlenderWorkerError(f"{action} completed without a worker result\n--- Blender output (tail) ---\n{self._tail(log)}")
        return json.loads(line[len(RESULT_PREFIX):])

    def move(self, h: float, v: float) -> dict[str, Any]:
        """Persist an absolute binocular fixation pose for normalized ``h, v``."""
        self._validate(h, v)
        return self._run("move", h, v)

    def reset(self) -> dict[str, Any]:
        """Persist the exact calibrated neutral fixation pose."""
        return self._run("reset")

    def render(self, output_path: str | Path | None = None) -> Path:
        """Render the current saved pose to a real 1024 × 1024 PNG."""
        if output_path is None:
            self._render_index += 1
            output = self.output_dir / f"eye_render_{self._render_index:04d}.png"
        else:
            candidate = Path(output_path)
            output = candidate if candidate.is_absolute() else self.output_dir / candidate
        try:
            return render(output, scene=self.scene, timeout=self.timeout)
        except RenderError as error:
            raise BlenderWorkerError(str(error)) from error
