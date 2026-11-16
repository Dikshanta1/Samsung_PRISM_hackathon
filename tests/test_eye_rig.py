"""Run inside Blender: validate naming, pivots, independence and gaze directions.

A render succeeding says nothing about the rig, so every direction is checked
by projecting the pupil centre through the scene camera and asserting that it
moves the expected way in the 1024 x 1024 image.
"""

from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from eye_rig import EYE_CENTERS, reset_eyes, set_eye_rotation, world_eye_center

ANGLE = 0.30  # radians used for direction checks (~17 degrees)
MIN_SHIFT_PX = 20.0  # required pupil shift along the commanded image axis
MAX_CROSS_PX = 3.0  # allowed drift along the other image axis
SIDES = tuple(EYE_CENTERS)


def near(a: Vector, b: Vector, epsilon: float = 1e-6) -> bool:
    return (a - b).length < epsilon


def pupil_world(side: str) -> Vector:
    """Geometric centre of the pupil mesh in world space."""
    obj = bpy.data.objects[f"Pupil_{side}"]
    points = [obj.matrix_world @ v.co for v in obj.data.vertices]
    return sum(points, Vector()) / len(points)


def pupil_pixel(side: str) -> Vector:
    """Pupil centre in image pixels: x grows right, y grows down."""
    scene = bpy.context.scene
    ndc = world_to_camera_view(scene, scene.camera, pupil_world(side))
    return Vector((ndc.x * scene.render.resolution_x, (1.0 - ndc.y) * scene.render.resolution_y))


def check_required_objects(rig: bpy.types.Object) -> None:
    required = ["Eye_L", "Eye_R", "Iris_L", "Iris_R", "Pupil_L", "Pupil_R", "EyeRig", "Camera", "FixationTarget"]
    for name in required:
        assert bpy.data.objects.get(name), f"Missing required object: {name}"
    for name in ("EyeBone_L", "EyeBone_R"):
        assert rig.pose.bones.get(name), f"Missing required bone: {name}"
    for side in SIDES:
        for feature in ("Iris", "Pupil"):
            parent = bpy.data.objects[f"{feature}_{side}"].parent
            assert parent and parent.name == f"Eye_{side}", f"{feature}_{side} is not parented to Eye_{side}"


def check_directions(rig: bpy.types.Object) -> None:
    """Up, Down, Left, Right and Reset for each eye, as seen by the camera."""
    # (label, pitch, yaw, expected image direction)
    cases = (
        ("up", ANGLE, 0.0, Vector((0, -1))),
        ("down", -ANGLE, 0.0, Vector((0, 1))),
        ("right", 0.0, ANGLE, Vector((1, 0))),
        ("left", 0.0, -ANGLE, Vector((-1, 0))),
    )
    reset_eyes(rig)
    neutral = {side: pupil_pixel(side) for side in SIDES}
    for side in SIDES:
        for label, pitch, yaw, expected in cases:
            reset_eyes(rig)
            set_eye_rotation(rig, side, pitch, yaw)
            shift = pupil_pixel(side) - neutral[side]
            along = shift.dot(expected)
            cross = abs(shift.x if expected.x == 0 else shift.y)
            assert along > MIN_SHIFT_PX, f"Eye_{side} {label}: pupil moved {along:.1f}px along expected axis (shift={tuple(shift)})"
            assert cross < MAX_CROSS_PX, f"Eye_{side} {label}: pupil drifted {cross:.1f}px off-axis (shift={tuple(shift)})"
            other = SIDES[1 - SIDES.index(side)]
            assert (pupil_pixel(other) - neutral[other]).length < 1e-3, f"Eye_{other} moved on Eye_{side} {label}"
        print(f"DIRECTIONS_OK Eye_{side} up/down/left/right")

    reset_eyes(rig)
    for side in SIDES:
        assert (pupil_pixel(side) - neutral[side]).length < 1e-3, f"Eye_{side} did not return to neutral on reset"


def check_pivots_and_independence(rig: bpy.types.Object) -> None:
    eyes = {side: bpy.data.objects[f"Eye_{side}"] for side in SIDES}
    reset_eyes(rig)
    centres = {side: world_eye_center(eyes[side]) for side in SIDES}
    rotations = {side: eyes[side].matrix_world.to_quaternion() for side in SIDES}
    for side in SIDES:
        assert near(centres[side], EYE_CENTERS[side]), f"Eye_{side} neutral centre is not at EYE_CENTERS"

    for side in SIDES:
        other = SIDES[1 - SIDES.index(side)]
        for pitch, yaw in ((ANGLE, 0.0), (0.0, ANGLE), (-ANGLE, -ANGLE)):
            reset_eyes(rig)
            set_eye_rotation(rig, side, pitch, yaw)
            assert near(world_eye_center(eyes[side]), centres[side]), f"Eye_{side} centre drifted at pitch={pitch}, yaw={yaw}"
            assert near(world_eye_center(eyes[other]), centres[other]), f"Eye_{other} centre moved with Eye_{side}"
            assert eyes[other].matrix_world.to_quaternion().rotation_difference(rotations[other]).angle < 1e-6, f"Eye_{other} rotated with Eye_{side}"
            # Pupil stays on the sphere: its distance from the eye centre is rotation-invariant.
            reset_eyes(rig)
            radius = (pupil_world(side) - centres[side]).length
            set_eye_rotation(rig, side, pitch, yaw)
            assert abs((pupil_world(side) - centres[side]).length - radius) < 1e-6, f"Pupil_{side} did not rotate rigidly about the centre"
    reset_eyes(rig)


def main() -> None:
    rig = bpy.data.objects.get("EyeRig")
    assert rig, "Missing required object: EyeRig"
    check_required_objects(rig)
    check_pivots_and_independence(rig)
    check_directions(rig)
    print("EYE_RIG_TEST_OK independent_bones=true centres_fixed=true directions=5/5")


if __name__ == "__main__":
    main()
