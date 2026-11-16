"""Optional CLI dataset helper; it does not start the official ten-frame pass by default."""
from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Render explicitly supplied eye poses through the public wrapper.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "dataset")
    parser.add_argument("--pose", action="append", type=parse_pose, required=True, help="Normalized H,V; repeat for multiple frames")
    args = parser.parse_args()
    eyes = Eyes(args.output_dir)
    try:
        for index, (h, v) in enumerate(args.pose):
            eyes.move(h, v)
            path = eyes.render(f"frame_{index:04d}.png")
            print(f"DATASET_FRAME index={index} h={h} v={v} path={path}")
    finally:
        eyes.reset()


if __name__ == "__main__":
    main()
