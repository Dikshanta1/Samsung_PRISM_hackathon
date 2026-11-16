"""Blender-runtime command worker used by :mod:`wrapper.eyes`.

This file must be run by Blender, never ordinary CPython:

    Blender --background --factory-startup blender/scene.blend --python-exit-code 1 \
        --python scripts/blender_worker.py -- move --h=1 --v=0
    ... -- reset
    ... -- render --h=1 --v=0 --output /absolute/path/frame.png

Each run loads the scene given on Blender's command line, sets one absolute
binocular fixation pose, measures it, optionally renders it, and prints exactly
one machine-readable line: ``WORKER_RESULT {json}`` or ``WORKER_ERROR reason``.
The .blend file is never saved, so the camera calibration and lighting stored
in it cannot be changed from here.
"""
from __future__ import annotations

import argparse
import json
from math import degrees
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from calibration import state, validate_input
from camera_setup import calibration_report, camera_state, projection_matrix, pupil_centres_px, verify_camera
from lighting_setup import lighting_state, verify_lighting
from render_frame import render_still

RESULT_PREFIX = "WORKER_RESULT "
ERROR_PREFIX = "WORKER_ERROR "
REQUIRED_OBJECTS = ("EyeRig", "Eye_L", "Eye_R", "Pupil_L", "Pupil_R", "FixationTarget")


class WorkerError(RuntimeError):
    """The requested action could not be carried out on the loaded scene."""


def require_eye_scene(expected: Path | None) -> None:
    """Fail clearly unless Blender loaded the intended file and it is the eye scene."""
    loaded = bpy.data.filepath
    if expected is not None:
        if not loaded:
            raise WorkerError(f"Blender did not load {expected}")
        if Path(loaded).resolve() != expected.resolve():
            raise WorkerError(f"Blender loaded {loaded}, expected {expected}")
    missing = [name for name in REQUIRED_OBJECTS if name not in bpy.data.objects]
    if missing:
        raise WorkerError(f"{loaded or 'the loaded file'} is not the eye scene: missing {', '.join(missing)}")


def eye_rotations_degrees() -> dict[str, list[float]]:
    """World-frame XYZ Euler angles ``[rx, ry, rz]`` of each posed eyeball, in degrees."""
    return {side: [degrees(angle) for angle in bpy.data.objects[f"Eye_{side}"].matrix_world.to_euler("XYZ")]
            for side in ("L", "R")}


def run(args: argparse.Namespace) -> dict[str, object]:
    require_eye_scene(args.scene)
    scene = bpy.context.scene
    h, v = (0.0, 0.0) if args.action == "reset" else (args.h, args.v)
    validate_input(h, v)
    verify_camera(scene)
    verify_lighting(scene)
    camera_before, lighting_before = camera_state(scene), lighting_state(scene)

    # state() writes absolute bone orientations computed from h and v alone, so
    # the result does not depend on any pose that was set before.
    result: dict[str, object] = {"action": args.action, "scene": bpy.data.filepath,
                                 "blender_version": bpy.app.version_string}
    result.update(state(h, v))
    result["eye_rotation_euler_xyz_degrees"] = eye_rotations_degrees()
    result["pupil_center_2D"] = pupil_centres_px(scene)
    result["camera_matrix"] = projection_matrix(scene)
    result["camera_calibration"] = calibration_report(scene)

    if args.action == "render":
        if args.output is None:
            raise WorkerError("render requires --output")
        result["output"] = render_still(args.output)["output"]

    if camera_state(scene) != camera_before:
        raise WorkerError("The locked camera changed while executing the command")
    if lighting_state(scene) != lighting_before:
        raise WorkerError("The lighting changed while executing the command")
    result["camera_fixed"] = True
    result["lighting_constant"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("move", "reset", "render"))
    parser.add_argument("--h", type=float, default=0.0)
    parser.add_argument("--v", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scene", type=Path, help="The .blend file Blender is expected to have loaded")
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(arguments)
    try:
        result = run(args)
    except Exception as error:  # one line for the wrapper, then re-raised for the exit code
        print(f"{ERROR_PREFIX}{type(error).__name__}: {error}", flush=True)
        raise
    print(RESULT_PREFIX + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
