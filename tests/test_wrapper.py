"""Ordinary-Python acceptance test for the public :class:`wrapper.eyes.Eyes`."""
from __future__ import annotations

from pathlib import Path
import hashlib
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wrapper.eyes import Eyes
from wrapper.renderer import png_size


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output_dir = Path(temporary)
        eyes = Eyes(output_dir)
        try:
            try:
                eyes.move(1.01, 0.0)
            except ValueError:
                print("INPUT_VALIDATION_OK")
            else:
                raise AssertionError("Out-of-range movement was accepted")

            left = eyes.move(-1.0, 0.0)
            assert max(left["angular_error_degrees"].values()) < 0.001
            left_png = eyes.render("left.png")
            assert png_size(left_png) == (1024, 1024) and left_png.stat().st_size > 10_000

            right = eyes.move(1.0, 0.0)
            assert max(right["angular_error_degrees"].values()) < 0.001
            right_png = eyes.render("right.png")
            assert png_size(right_png) == (1024, 1024) and right_png.stat().st_size > 10_000
            assert digest(left_png) != digest(right_png), "Opposite poses produced identical actual PNGs"

            centre = eyes.reset()
            assert centre["inputs"] == {"h": 0.0, "v": 0.0}
            reset_png = eyes.render()
            assert png_size(reset_png) == (1024, 1024)
            print(f"WRAPPER_TEST_OK blender=true movement=true reset=true png={reset_png}")
        finally:
            eyes.reset()


if __name__ == "__main__":
    main()
