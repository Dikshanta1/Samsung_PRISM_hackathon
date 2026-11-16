"""Blender-runtime calibration and absolute binocular fixation operations."""
from __future__ import annotations
from math import degrees
from pathlib import Path
import argparse
import json
import sys
import bpy
from mathutils import Matrix, Quaternion, Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_rig import EYE_CENTERS

EYE_FORWARD_LOCAL = Vector((0.0, -1.0, 0.0))
TARGET_DISTANCE_M = 0.350
TARGET_BOUND_M = 0.050
NEUTRAL_TARGET = Vector((0.0, -0.483, 0.055))

def validate_input(h: float, v: float) -> None:
    if not (-1.0 <= h <= 1.0 and -1.0 <= v <= 1.0):
        raise ValueError(f"h and v must be in [-1, +1], received h={h}, v={v}")

def target_for_input(h: float, v: float) -> Vector:
    """Map h to world X and v to world Z within the ±5 cm target bounds."""
    validate_input(h, v)
    return NEUTRAL_TARGET + Vector((TARGET_BOUND_M * h, 0.0, TARGET_BOUND_M * v))

def desired_orientation(eye_center: Vector, target: Vector) -> Quaternion:
    """Map the eye's local -Y optical axis to a target direction."""
    return (target - eye_center).normalized().to_track_quat("-Y", "Z")

def _set_bone_for_world_orientation(rig: bpy.types.Object, side: str, orientation: Quaternion) -> None:
    """Convert a requested eye-world quaternion to a pose-bone basis matrix."""
    pose_bone = rig.pose.bones[f"EyeBone_{side}"]
    rest = rig.data.bones[f"EyeBone_{side}"].matrix_local.to_4x4()
    # A pure rotation matrix rotates points around world origin. Build its
    # conjugate around this bone head so the eyeball's physical centre stays
    # fixed while its optical axis changes.
    pivot = EYE_CENTERS[side]
    around_eye_centre = (
        Matrix.Translation(pivot)
        @ orientation.to_matrix().to_4x4()
        @ Matrix.Translation(-pivot)
    )
    pose_bone.matrix_basis = rest.inverted() @ around_eye_centre @ rest

def set_fixation(h: float, v: float) -> Vector:
    """Set an absolute, non-accumulating binocular fixation pose."""
    target = target_for_input(h, v)
    rig = bpy.data.objects["EyeRig"]
    bpy.data.objects["FixationTarget"].location = target
    for side in ("L", "R"):
        _set_bone_for_world_orientation(rig, side, desired_orientation(EYE_CENTERS[side], target))
    bpy.context.view_layer.update()
    return target

def reset() -> Vector:
    """Restore neutral pose directly rather than by reversing a prior rotation."""
    return set_fixation(0.0, 0.0)

def actual_gaze_direction(side: str) -> Vector:
    return (bpy.data.objects[f"Eye_{side}"].matrix_world.to_3x3() @ EYE_FORWARD_LOCAL).normalized()

def angular_error_degrees(side: str, target: Vector) -> float:
    expected = (target - EYE_CENTERS[side]).normalized()
    return degrees(actual_gaze_direction(side).angle(expected))

def state(h: float, v: float) -> dict[str, object]:
    target = set_fixation(h, v)
    return {"inputs": {"h": h, "v": v}, "fixation_target_world_m": list(target),
            "angular_error_degrees": {s: angular_error_degrees(s, target) for s in ("L", "R")},
            "world_eye_rotations_quaternion": {s: list(bpy.data.objects[f"Eye_{s}"].matrix_world.to_quaternion()) for s in ("L", "R")}}

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--h", type=float, default=0.0)
    parser.add_argument("--v", type=float, default=0.0)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--save", action="store_true", help="Persist the requested pose in the loaded .blend file")
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)
    result = state(args.h, args.v)
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(result))

if __name__ == "__main__":
    main()
