"""Blender-runtime still render of the current eye pose through the locked camera.

Run by ``wrapper/renderer.py``:

    Blender --background scene.blend --python-exit-code 1 \
        --python blender/render_frame.py -- --output /absolute/path/frame.png

``render_still`` never moves the camera or the lights and never saves the
.blend file. It refuses to render if either deviates from the locked
configuration, and it checks that both are unchanged afterwards.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_setup import RESOLUTION_PX, camera_state, pupil_centres_px, verify_camera
from lighting_setup import lighting_state, verify_lighting

RESULT_PREFIX = "RENDER_RESULT "


class RenderFailure(RuntimeError):
    """The frame could not be rendered as specified."""


def render_still(output_path: Path) -> dict[str, object]:
    """Render the scene as it is now to ``output_path`` and describe the result."""
    output_path = Path(output_path).resolve()
    if output_path.suffix.lower() != ".png":
        raise RenderFailure(f"Output must be a .png file, received {output_path.name!r}")
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    verify_camera(scene)
    verify_lighting(scene)
    camera_before, lighting_before = camera_state(scene), lighting_state(scene)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    previous_filepath = scene.render.filepath
    scene.render.filepath = str(output_path)
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as error:
        raise RenderFailure(f"Blender failed to render {output_path}: {error}") from error
    finally:
        scene.render.filepath = previous_filepath

    if camera_state(scene) != camera_before:
        raise RenderFailure("The locked camera changed during the render")
    if lighting_state(scene) != lighting_before:
        raise RenderFailure("The lighting changed during the render")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RenderFailure(f"Blender reported success but wrote no image at {output_path}")
    return {
        "output": str(output_path),
        "resolution_px": [RESOLUTION_PX, RESOLUTION_PX],
        "camera_fixed": True,
        "lighting_constant": True,
        "pupil_center_2D": pupil_centres_px(scene),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)
    try:
        result = render_still(args.output)
    except Exception as error:  # reported on one line for the wrapper, then re-raised for the exit code
        print(f"RENDER_ERROR {type(error).__name__}: {error}", flush=True)
        raise
    print(RESULT_PREFIX + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
