"""Blender-runtime calibration and absolute, coordinated (conjugate) gaze.

Gaze model
----------
Both eyes always turn together by the same rotation, as in a conjugate
("version") eye movement: the gaze direction is the line from the eye midpoint
(the cyclopean eye) to the fixation target, and each eyeball is rotated about
its own centre so that its optical axis is parallel to that line.

* Neutral (h = v = 0): the target is 35 cm straight ahead of the midpoint, so
  both eyes look exactly forward, parallel, with zero rotation.
* h = +1: both eyes turn right by the same angle, atan(5 / 35) = 8.13 degrees;
  v = +1 turns both up by the same angle; diagonals combine the two.

The eyes therefore never cross or diverge: their rotations are identical in
every pose, so the two pupils always move together by the same amount.
"""
from __future__ import annotations
from math import degrees
from pathlib import Path
import argparse
import json
import sys
import bpy
from mathutils import Quaternion, Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_rig import EYE_CENTERS, pupil_centre_world
import eyelids

TARGET_DISTANCE_M = 0.350
CAMERA_DISTANCE_M = 0.400
TARGET_BOUND_M = 0.050
FACE_FORWARD_WORLD = Vector((0.0, -1.0, 0.0))

def eye_midpoint() -> Vector:
    """Design midpoint of the two eye centres (the cyclopean eye)."""
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

def eye_midpoint_world(rig: bpy.types.Object) -> Vector:
    """Actual midpoint of the two rotation centres."""
    return (eye_center_world(rig, "L") + eye_center_world(rig, "R")) / 2

def gaze_direction(midpoint: Vector, target: Vector) -> Vector:
    """The shared gaze direction: from the eye midpoint toward the fixation target."""
    return (target - midpoint).normalized()

def desired_orientation(direction: Vector) -> Quaternion:
    """Map the eye's local -Y optical axis onto ``direction``, with no roll (local +Z stays up)."""
    return direction.to_track_quat("-Y", "Z")

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
    """Set an absolute, non-accumulating, coordinated gaze pose: both eyes get the same rotation."""
    target = target_for_input(h, v)
    rig = bpy.data.objects["EyeRig"]
    bpy.data.objects["FixationTarget"].location = target
    direction = gaze_direction(eye_midpoint_world(rig), target)
    orientation = desired_orientation(direction)
    for side in ("L", "R"):
        _set_bone_for_world_orientation(rig, side, orientation)
    eyelids.apply({"L": direction, "R": direction})
    bpy.context.view_layer.update()
    return target

def reset() -> Vector:
    """Restore neutral pose directly rather than by reversing a prior rotation."""
    return set_fixation(0.0, 0.0)

def actual_eye_center(side: str) -> Vector:
    """Measured world centre of the posed eyeball object."""
    return bpy.data.objects[f"Eye_{side}"].matrix_world.translation.copy()

def actual_gaze_direction(side: str) -> Vector:
    """Measured optical axis: posed eyeball centre to posed pupil centre (pupil-margin landmark).

    This reads the evaluated scene rather than the constants and matrices used
    to set the pose, so it can expose a wrong pivot or a misplaced rig.
    """
    return (pupil_centre_world(side) - actual_eye_center(side)).normalized()

def actual_eye_midpoint() -> Vector:
    return (actual_eye_center("L") + actual_eye_center("R")) / 2

def angular_error_degrees(side: str, target: Vector) -> float:
    """Angle between an eye's measured optical axis and the shared gaze direction (midpoint -> target)."""
    expected = gaze_direction(actual_eye_midpoint(), target)
    return degrees(actual_gaze_direction(side).angle(expected))

def binocular_alignment() -> dict[str, float]:
    """How well the two eyes move together, measured from the posed scene.

    ``gaze_angle_between_eyes_degrees``: angle between the two measured optical
    axes (0 = perfectly parallel). ``rotation_difference_degrees``: angle of the
    rotation taking one eyeball's world orientation to the other's (0 = the two
    eyes have exactly the same rotation, including roll).
    """
    left = bpy.data.objects["Eye_L"].matrix_world.to_quaternion()
    right = bpy.data.objects["Eye_R"].matrix_world.to_quaternion()
    return {"gaze_angle_between_eyes_degrees": degrees(actual_gaze_direction("L").angle(actual_gaze_direction("R"))),
            "rotation_difference_degrees": degrees(left.rotation_difference(right).angle)}

def state(h: float, v: float) -> dict[str, object]:
    target = set_fixation(h, v)
    return {"inputs": {"h": h, "v": v}, "fixation_target_world_m": list(target),
            "angular_error_degrees": {s: angular_error_degrees(s, target) for s in ("L", "R")},
            "binocular_alignment": binocular_alignment(),
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
