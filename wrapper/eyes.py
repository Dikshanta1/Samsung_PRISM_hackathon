"""Simple external API for the Samsung PRISM binocular-eye Blender scene.

    from wrapper.eyes import Eyes

    eyes = Eyes()
    eyes.move(1, 0)
    eyes.render()
    eyes.reset()

This module is ordinary Python and never imports ``bpy``. Every call starts
Blender in background mode on the real ``scene.blend`` and runs
``scripts/blender_worker.py`` inside Blender's own Python runtime.

The current pose ``(h, v)`` is held by the ``Eyes`` object and sent to Blender
with each command as an absolute fixation, so movements never accumulate. The
scene file is never saved: it always holds the calibrated neutral pose, the
locked camera and the constant lighting.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
import json
import subprocess
from typing import Any

from .blender_runner import blender_executable
from .renderer import RenderError, render_with_details

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = ROOT / "scene.blend"
DEFAULT_OUTPUT_DIR = ROOT / "outputs"
WORKER = ROOT / "scripts" / "blender_worker.py"
RESULT_PREFIX = "WORKER_RESULT "
ERROR_PREFIX = "WORKER_ERROR "


class BlenderWorkerError(RuntimeError):
    """Blender could not load, control or render the real eye scene."""


def _coordinate(name: str, value: Any) -> float:
    """Return ``value`` as a float in [-1, +1], or raise ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in [-1, +1], received {value!r}")
    number = float(value)
    if not isfinite(number) or not -1.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [-1, +1], received {value!r}")
    return number


class Eyes:
    """Control and render the Blender eye scene through background Blender processes.

    ``output_dir`` is where ``render()`` writes images (default ``outputs/``);
    ``scene`` overrides the .blend file; ``timeout`` is the limit in seconds for
    each Blender run.
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        *,
        scene: str | Path | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.scene = Path(scene).expanduser().resolve() if scene else DEFAULT_SCENE
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else DEFAULT_OUTPUT_DIR
        self.timeout = timeout
        self._pose = (0.0, 0.0)
        self._render_index = 0
        self.last_render: dict[str, Any] | None = None
        if not self.scene.is_file():
            raise FileNotFoundError(f"Blender scene not found: {self.scene}")

    @property
    def position(self) -> tuple[float, float]:
        """The current ``(h, v)``; ``(0.0, 0.0)`` is the neutral pose."""
        return self._pose

    @staticmethod
    def _tail(text: str, limit: int = 20) -> str:
        return "\n".join(text.strip().splitlines()[-limit:])

    def _run(self, action: str, h: float, v: float) -> dict[str, Any]:
        try:
            blender = blender_executable()
        except FileNotFoundError as error:
            raise BlenderWorkerError(str(error)) from error
        command = [
            str(blender), "--background", "--factory-startup", str(self.scene), "--python-exit-code", "1",
            "--python", str(WORKER), "--", action, f"--h={h!r}", f"--v={v!r}", "--scene", str(self.scene),
        ]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise BlenderWorkerError(f"Blender {action} did not finish within {self.timeout:g} s") from error
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
        """Fixate both eyes for normalised ``h, v`` in [-1, +1] and return the measured pose.

        ``h = +1`` looks image-right, ``v = +1`` looks up. The pose is absolute:
        it replaces the previous one. An out-of-range or non-numeric input
        raises ``ValueError`` and leaves the current pose unchanged.
        """
        h, v = _coordinate("h", h), _coordinate("v", v)
        state = self._run("move", h, v)
        self._pose = (h, v)
        return state

    def reset(self) -> dict[str, Any]:
        """Return both eyes to the calibrated neutral pose and return the measured pose."""
        state = self._run("reset", 0.0, 0.0)
        self._pose = (0.0, 0.0)
        return state

    def render(self, output_path: str | Path | None = None, *, pupil_mask: bool | str | Path = False) -> Path:
        """Render the current pose to a 1024 x 1024 PNG and return its absolute path.

        With no argument the image is ``output_dir/eye_render_NNNN.png``. A
        relative path is placed under ``output_dir``; an absolute path is used
        as given. Blender's report for the frame is kept in ``last_render``.

        ``pupil_mask=True`` also writes ``<image>_pupil_mask.png`` beside the
        image (or pass a path, resolved like ``output_path``): the same view
        with only the textured pupils, white on black. Its path and the mask
        centroids are reported in ``last_render["pupil_mask"]``.
        """
        if output_path is None:
            self._render_index += 1
            output = self.output_dir / f"eye_render_{self._render_index:04d}.png"
        else:
            candidate = Path(output_path).expanduser()
            output = candidate if candidate.is_absolute() else self.output_dir / candidate
        mask = None
        if pupil_mask is True:
            mask = output.with_name(f"{output.stem}_pupil_mask.png")
        elif pupil_mask:
            candidate = Path(pupil_mask).expanduser()
            mask = candidate if candidate.is_absolute() else self.output_dir / candidate
        try:
            path, details = render_with_details(output, scene=self.scene, timeout=self.timeout, pose=self._pose,
                                                pupil_mask=mask)
        except RenderError as error:
            raise BlenderWorkerError(str(error)) from error
        self.last_render = details
        return path
