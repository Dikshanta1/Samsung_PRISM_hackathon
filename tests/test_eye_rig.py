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
from eye_rig import EYE_CENTERS, pupil_centre_world, zero_pose, set_eye_rotation, world_eye_center

ANGLE = 0.30  # radians used for direction checks (~17 degrees)
MIN_SHIFT_PX = 15.0  # required pupil shift along the commanded image axis (~25 px at 17 degrees)
MAX_CROSS_PX = 3.0  # allowed drift along the other image axis
SIDES = tuple(EYE_CENTERS)


def near(a: Vector, b: Vector, epsilon: float = 1e-6) -> bool:
    return (a - b).length < epsilon


def pupil_world(side: str) -> Vector:
    """Centre of the pupil margin in world space."""
    return pupil_centre_world(side)


def pupil_pixel(side: str) -> Vector:
    """Pupil centre in image pixels: x grows right, y grows down."""
    scene = bpy.context.scene
    ndc = world_to_camera_view(scene, scene.camera, pupil_world(side))
    return Vector((ndc.x * scene.render.resolution_x, (1.0 - ndc.y) * scene.render.resolution_y))


def check_required_objects(rig: bpy.types.Object) -> None:
    required = ["Eye_L", "Eye_R", "Pupil_L", "Pupil_R", "EyeRig", "FaceRig", "CC_Base_Body", "Camera", "FixationTarget"]
    for name in required:
        assert bpy.data.objects.get(name), f"Missing required object: {name}"
    for name in ("EyeBone_L", "EyeBone_R"):
        assert rig.pose.bones.get(name), f"Missing required bone: {name}"
    assert rig.parent and rig.parent.name == "FaceRig" and rig.parent_bone == "CC_Base_Head", "EyeRig must ride on the head bone"
    for side in SIDES:
        eye = bpy.data.objects[f"Eye_{side}"]
        assert eye.parent == rig and eye.parent_type == "BONE" and eye.parent_bone == f"EyeBone_{side}", f"Eye_{side} is not a rigid child of EyeBone_{side}"
        assert not any(m.type == "ARMATURE" for m in eye.modifiers), f"Eye_{side} must not be skinned"
        materials = [m.name for m in eye.data.materials]
        assert materials and all(n.startswith("Std_Eye_") for n in materials), f"Eye_{side} materials: {materials}"
        pupil = bpy.data.objects[f"Pupil_{side}"]
        assert pupil.parent == eye, f"Pupil_{side} is not parented to Eye_{side}"
        assert pupil.hide_render, f"Pupil_{side} landmark must not render"
    # Every image the scene uses must be inside the .blend (no paths to the author's machine).
    for image in bpy.data.images:
        if image.users and image.source == "FILE":
            assert image.packed_file is not None, f"Image {image.name} is not packed"


def check_directions(rig: bpy.types.Object) -> None:
    """Up, Down, Left, Right and Reset for each eye, as seen by the camera."""
    # (label, pitch, yaw, expected image direction)
    cases = (
        ("up", ANGLE, 0.0, Vector((0, -1))),
        ("down", -ANGLE, 0.0, Vector((0, 1))),
        ("right", 0.0, ANGLE, Vector((1, 0))),
        ("left", 0.0, -ANGLE, Vector((-1, 0))),
    )
    zero_pose(rig)
    neutral = {side: pupil_pixel(side) for side in SIDES}
    for side in SIDES:
        for label, pitch, yaw, expected in cases:
            zero_pose(rig)
            set_eye_rotation(rig, side, pitch, yaw)
            shift = pupil_pixel(side) - neutral[side]
            along = shift.dot(expected)
            cross = abs(shift.x if expected.x == 0 else shift.y)
            assert along > MIN_SHIFT_PX, f"Eye_{side} {label}: pupil moved {along:.1f}px along expected axis (shift={tuple(shift)})"
            assert cross < MAX_CROSS_PX, f"Eye_{side} {label}: pupil drifted {cross:.1f}px off-axis (shift={tuple(shift)})"
            other = SIDES[1 - SIDES.index(side)]
            assert (pupil_pixel(other) - neutral[other]).length < 1e-3, f"Eye_{other} moved on Eye_{side} {label}"
        print(f"DIRECTIONS_OK Eye_{side} up/down/left/right")

    zero_pose(rig)
    for side in SIDES:
        assert (pupil_pixel(side) - neutral[side]).length < 1e-3, f"Eye_{side} did not return to neutral on reset"


def check_pivots_and_independence(rig: bpy.types.Object) -> None:
    eyes = {side: bpy.data.objects[f"Eye_{side}"] for side in SIDES}
    zero_pose(rig)
    centres = {side: world_eye_center(eyes[side]) for side in SIDES}
    rotations = {side: eyes[side].matrix_world.to_quaternion() for side in SIDES}
    for side in SIDES:
        assert near(centres[side], EYE_CENTERS[side]), f"Eye_{side} neutral centre is not at EYE_CENTERS"

    for side in SIDES:
        other = SIDES[1 - SIDES.index(side)]
        for pitch, yaw in ((ANGLE, 0.0), (0.0, ANGLE), (-ANGLE, -ANGLE)):
            zero_pose(rig)
            set_eye_rotation(rig, side, pitch, yaw)
            assert near(world_eye_center(eyes[side]), centres[side]), f"Eye_{side} centre drifted at pitch={pitch}, yaw={yaw}"
            assert near(world_eye_center(eyes[other]), centres[other]), f"Eye_{other} centre moved with Eye_{side}"
            assert eyes[other].matrix_world.to_quaternion().rotation_difference(rotations[other]).angle < 1e-6, f"Eye_{other} rotated with Eye_{side}"
            # Pupil stays on the sphere: its distance from the eye centre is rotation-invariant.
            zero_pose(rig)
            radius = (pupil_world(side) - centres[side]).length
            set_eye_rotation(rig, side, pitch, yaw)
            assert abs((pupil_world(side) - centres[side]).length - radius) < 1e-6, f"Pupil_{side} did not rotate rigidly about the centre"
    zero_pose(rig)


def main() -> None:
    rig = bpy.data.objects.get("EyeRig")
    assert rig, "Missing required object: EyeRig"
    check_required_objects(rig)
    check_pivots_and_independence(rig)
    check_directions(rig)
    print("EYE_RIG_TEST_OK independent_bones=true centres_fixed=true directions=5/5")


if __name__ == "__main__":
    main()
