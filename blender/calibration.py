"""Blender-runtime calibration and absolute binocular fixation operations."""
from __future__ import annotations
from math import degrees
from pathlib import Path
import argparse
import json
import sys
import bpy
from mathutils import Quaternion, Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_rig import EYE_CENTERS

TARGET_DISTANCE_M = 0.350
CAMERA_DISTANCE_M = 0.400
TARGET_BOUND_M = 0.050
FACE_FORWARD_WORLD = Vector((0.0, -1.0, 0.0))

def eye_midpoint() -> Vector:
    """Design midpoint of the two eye centres, (0, -0.133, 0.055) m."""
    return (EYE_CENTERS["L"] + EYE_CENTERS["R"]) / 2

NEUTRAL_TARGET = eye_midpoint() + TARGET_DISTANCE_M * FACE_FORWARD_WORLD

def eye_center_world(rig: bpy.types.Object, side: str) -> Vector:
    """Actual world rotation centre: the eye bone's head under the rig's transform."""
    return rig.matrix_world @ rig.data.bones[f"EyeBone_{side}"].head_local

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
    """Convert a requested eye-world quaternion to a rotation-only pose-bone basis.

    With A the armature's world rotation and R the bone's rest rotation, the
    eye's world rotation is A @ D, where D is the pose delta in armature space
    (the eye mesh is unrotated in the armature's rest space). Solving for the
    requested orientation q gives D = A^-1 @ q, and the pose-bone basis is D
    expressed in the bone's rest frame: R^-1 @ D @ R. No translation is
    written, so the eyeball can only rotate about the bone head.
    """
    pose_bone = rig.pose.bones[f"EyeBone_{side}"]
    rest_rotation = rig.data.bones[f"EyeBone_{side}"].matrix_local.to_3x3()
    armature_rotation = rig.matrix_world.to_quaternion().to_matrix()
    delta = armature_rotation.inverted() @ orientation.to_matrix()
    pose_bone.matrix_basis = (rest_rotation.inverted() @ delta @ rest_rotation).to_4x4()

def set_fixation(h: float, v: float) -> Vector:
    """Set an absolute, non-accumulating binocular fixation pose."""
    target = target_for_input(h, v)
    rig = bpy.data.objects["EyeRig"]
    bpy.data.objects["FixationTarget"].location = target
    for side in ("L", "R"):
        _set_bone_for_world_orientation(rig, side, desired_orientation(eye_center_world(rig, side), target))
    bpy.context.view_layer.update()
    return target

def reset() -> Vector:
    """Restore neutral pose directly rather than by reversing a prior rotation."""
    return set_fixation(0.0, 0.0)

def actual_eye_center(side: str) -> Vector:
    """Measured world centre of the posed eyeball object."""
    return bpy.data.objects[f"Eye_{side}"].matrix_world.translation.copy()

def actual_gaze_direction(side: str) -> Vector:
    """Measured optical axis: posed eyeball centre to posed pupil centre.

    This reads the evaluated scene rather than the constants and matrices used
    to set the pose, so it can expose a wrong pivot or a misplaced rig.
    """
    pupil = bpy.data.objects[f"Pupil_{side}"].matrix_world.translation
    return (pupil - actual_eye_center(side)).normalized()

def angular_error_degrees(side: str, target: Vector) -> float:
    expected = (target - actual_eye_center(side)).normalized()
    return degrees(actual_gaze_direction(side).angle(expected))

def convergence(target: Vector) -> dict[str, float]:
    """Closest approach of the two measured gaze rays, and its offset from the target."""
    p1, d1 = actual_eye_center("L"), actual_gaze_direction("L")
    p2, d2 = actual_eye_center("R"), actual_gaze_direction("R")
    w = p1 - p2
    b, d, e = d1.dot(d2), d1.dot(w), d2.dot(w)
    denominator = 1.0 - b * b
    if denominator < 1e-12:
        return {"ray_miss_m": float("inf"), "vergence_point_error_m": float("inf")}
    q1 = p1 + ((b * e - d) / denominator) * d1
    q2 = p2 + ((e - b * d) / denominator) * d2
    return {"ray_miss_m": (q1 - q2).length, "vergence_point_error_m": ((q1 + q2) / 2 - target).length}

def state(h: float, v: float) -> dict[str, object]:
    target = set_fixation(h, v)
    return {"inputs": {"h": h, "v": v}, "fixation_target_world_m": list(target),
            "angular_error_degrees": {s: angular_error_degrees(s, target) for s in ("L", "R")},
            "convergence": convergence(target),
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
