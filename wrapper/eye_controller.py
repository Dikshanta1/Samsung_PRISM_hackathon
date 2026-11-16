"""Public ordinary-Python controller for absolute Blender eye fixation."""
from __future__ import annotations
from pathlib import Path
import json
import subprocess
from .blender_runner import blender_executable
from .renderer import render as render_frame

class EyeController:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.scene = self.project_root / "blender" / "scene.blend"
        self.metadata = self.project_root / "metadata" / "latest_gaze.json"

    def move(self, h: float, v: float) -> dict[str, object]:
        if not (-1.0 <= h <= 1.0 and -1.0 <= v <= 1.0):
            raise ValueError("h and v must be in [-1, +1]")
        command = [str(blender_executable()), "--background", str(self.scene), "--python",
                   str(self.project_root / "blender" / "calibration.py"), "--", "--h", str(h), "--v", str(v),
                   "--metadata", str(self.metadata), "--save"]
        subprocess.run(command, check=True, text=True)
        return json.loads(self.metadata.read_text(encoding="utf-8"))

    def reset(self) -> dict[str, object]:
        return self.move(0.0, 0.0)

    def render(self, output_path: str | Path) -> Path:
        """Render the current eye position to a 1024 x 1024 PNG and return its path."""
        return render_frame(output_path, scene=self.scene)
