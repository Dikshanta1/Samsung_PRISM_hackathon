"""Render a list of eye poses through the public wrapper and write a manifest.

    python3 scripts/generate_dataset.py --output-dir outputs/demo --pose=-1,0 --pose=0,1

Each ``--pose=H,V`` becomes ``frame_NNNN.png`` in the output directory, and
``dataset.json`` records the input, the image and Blender's measurements for
every frame. It renders only the poses it is given; it does not start the
official ten-frame pass by default.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wrapper.eyes import Eyes


def parse_pose(value: str) -> tuple[float, float]:
    try:
        h_text, v_text = value.split(",", 1)
        return float(h_text), float(v_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Pose must be H,V, for example -1,0") from error


def generate(output_dir: Path, poses: list[tuple[float, float]], *, scene: Path | None = None) -> Path:
    """Render ``poses`` into ``output_dir`` and return the path of ``dataset.json``."""
    eyes = Eyes(output_dir, scene=scene)
    frames = []
    for index, (h, v) in enumerate(poses):
        eyes.move(h, v)
        path = eyes.render(f"frame_{index:04d}.png")
        report = eyes.last_render or {}
        frames.append({
            "frame": index,
            "input": {"h": h, "v": v},
            "image": path.name,
            "eye_rotation_euler_xyz_degrees": report.get("eye_rotation_euler_xyz_degrees"),
            "pupil_center_2D": report.get("pupil_center_2D"),
            "camera_matrix": report.get("camera_matrix"),
        })
        print(f"DATASET_FRAME index={index} h={h} v={v} path={path}")
    manifest = eyes.output_dir / "dataset.json"
    manifest.write_text(json.dumps({"scene": str(eyes.scene), "frames": frames}, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Render explicitly supplied eye poses through the public wrapper.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "dataset")
    parser.add_argument("--pose", action="append", type=parse_pose, required=True, help="Normalized H,V; repeat for multiple frames")
    args = parser.parse_args()
    print(f"DATASET_MANIFEST {generate(args.output_dir, args.pose)}")


if __name__ == "__main__":
    main()
