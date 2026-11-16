"""Run inside Blender: validate naming, independent rotations, and eye centres."""

from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from eye_rig import EYE_CENTERS, reset_eyes, set_eye_rotation, world_eye_center


def near(a: Vector, b: Vector, epsilon: float = 1e-6) -> bool:
    return (a - b).length < epsilon


def main() -> None:
    required = ["Eye_L", "Eye_R", "Iris_L", "Iris_R", "Pupil_L", "Pupil_R", "EyeRig", "Camera", "FixationTarget"]
    for name in required:
        assert bpy.data.objects.get(name), f"Missing required object: {name}"
    rig = bpy.data.objects["EyeRig"]
    for name in ("EyeBone_L", "EyeBone_R"):
        assert rig.pose.bones.get(name), f"Missing required bone: {name}"

    left, right = bpy.data.objects["Eye_L"], bpy.data.objects["Eye_R"]
    reset_eyes(rig)
    initial_left, initial_right = world_eye_center(left), world_eye_center(right)
    initial_left_pupil_vector = bpy.data.objects["Pupil_L"].matrix_world.translation - initial_left
    assert near(initial_left, EYE_CENTERS["L"])
    assert near(initial_right, EYE_CENTERS["R"])
    initial_right_rotation = right.matrix_world.to_quaternion().copy()

    set_eye_rotation(rig, "L", 0.25, 0.0)
    assert near(world_eye_center(left), initial_left), "Left eye centre drifted while rotating"
    assert near(world_eye_center(right), initial_right), "Right eye centre changed on left-only rotation"
    assert right.matrix_world.to_quaternion().rotation_difference(initial_right_rotation).angle < 1e-6, "Right eye rotated with left eye"
    moved_left_pupil_vector = bpy.data.objects["Pupil_L"].matrix_world.translation - left.matrix_world.translation
    assert (moved_left_pupil_vector - initial_left_pupil_vector).length > 0.005, "Pupil did not move with left-eye rotation"

    reset_eyes(rig)
    set_eye_rotation(rig, "R", -0.25, 0.0)
    assert near(world_eye_center(left), initial_left), "Left eye centre changed on right-only rotation"
    assert near(world_eye_center(right), initial_right), "Right eye centre drifted while rotating"
    reset_eyes(rig)
    print("EYE_RIG_TEST_OK independent_bones=true centres_fixed=true")


if __name__ == "__main__":
    main()
