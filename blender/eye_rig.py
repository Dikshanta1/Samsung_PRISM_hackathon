"""Blender-only construction and verification helpers for the two-eye rig."""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector


# The face looks along world -Y, so the subject's own left is world +X. "L" and
# "R" follow the Blender / Character Creator rig convention: they are the
# subject's anatomical left and right eyes. Seen from the camera, Eye_L is
# therefore on the right of the image and Eye_R on the left.
#
# These are the eyeball rotation centres of the imported Character Creator head
# (sphere fitted to the sclera; 66.84 mm apart, 17.6 mm sclera radius). The
# builder moves the whole character so the fitted centres land on these values
# and refuses to build if they are more than ``CENTRE_TOLERANCE_M`` away.
EYE_MIDPOINT = Vector((0.0, -0.0265, 1.7216))
HALF_INTEROCULAR_M = 0.03342
EYE_CENTERS = {
    "L": EYE_MIDPOINT + Vector((HALF_INTEROCULAR_M, 0.0, 0.0)),
    "R": EYE_MIDPOINT - Vector((HALF_INTEROCULAR_M, 0.0, 0.0)),
}
CENTRE_TOLERANCE_M = 3e-4
BONE_LENGTH_M = 0.02


class PupilLandmarkError(RuntimeError):
    """A Pupil_* landmark is missing or malformed."""


def _parent_to_bone(obj: bpy.types.Object, armature: bpy.types.Object, bone_name: str) -> None:
    """Parent an object to a pose bone while retaining its world transform."""
    pose_bone = armature.pose.bones[bone_name]
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    obj.matrix_parent_inverse = (armature.matrix_world @ pose_bone.matrix).inverted()
    obj.matrix_world = world


def create_eye_armature() -> bpy.types.Object:
    """Two non-deforming bones whose heads are the eyeball rotation centres."""
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    armature = bpy.context.active_object
    armature.name = "EyeRig"
    armature.data.name = "EyeRigData"
    edit_bones = armature.data.edit_bones
    edit_bones.remove(edit_bones[0])

    for side, center in EYE_CENTERS.items():
        bone = edit_bones.new(f"EyeBone_{side}")
        bone.head = center
        bone.tail = center + Vector((0, 0, BONE_LENGTH_M))
        bone.use_deform = False

    bpy.ops.object.mode_set(mode="OBJECT")
    armature.show_in_front = True
    return armature


def attach_eye(side: str, mesh: bpy.types.Mesh, armature: bpy.types.Object, scene: bpy.types.Scene) -> bpy.types.Object:
    """Make ``Eye_<side>`` from a world-space eyeball mesh centred on ``EYE_CENTERS[side]``.

    The mesh is re-expressed about the rotation centre, so the object origin is
    the pivot, its rest rotation is identity, and it is a rigid child of
    ``EyeBone_<side>``: posing the bone can only rotate it about its centre.
    """
    center = EYE_CENTERS[side]
    mesh.transform(Matrix.Translation(-center))
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    eye = bpy.data.objects.new(f"Eye_{side}", mesh)
    scene.collection.objects.link(eye)
    eye.location = center
    bpy.context.view_layer.update()
    _parent_to_bone(eye, armature, f"EyeBone_{side}")
    return eye


def create_pupil_landmark(side: str, eye: bpy.types.Object, centre_world: Vector, ring_world: list[Vector],
                          scene: bpy.types.Scene) -> bpy.types.Object:
    """Invisible open cap on the iris whose margin is the pupil edge painted in the texture.

    ``pupil_centre_local`` takes the pupil centre as the mean of
    this cap's open-margin vertices, so the landmark follows the eyeball
    exactly and never appears in a render.
    """
    inverse = eye.matrix_world.inverted()
    mesh = bpy.data.meshes.new(f"Pupil_{side}")
    vertices = [inverse @ centre_world] + [inverse @ point for point in ring_world]
    count = len(ring_world)
    faces = [(0, 1 + k, 1 + (k + 1) % count) for k in range(count)]
    mesh.from_pydata([tuple(v) for v in vertices], [], faces)
    mesh.update()
    pupil = bpy.data.objects.new(f"Pupil_{side}", mesh)
    scene.collection.objects.link(pupil)
    pupil.parent = eye
    pupil.matrix_parent_inverse.identity()
    pupil.hide_render = True
    pupil.visible_shadow = False
    pupil.display_type = "WIRE"
    pupil.show_in_front = True
    return pupil


def set_eye_rotation(armature: bpy.types.Object, side: str, pitch: float, yaw: float) -> None:
    """Rotate the named eye about its centre, in radians.

    Convention (face looks along world -Y, camera looks along +Y):
    * ``pitch > 0`` turns the gaze up (world +Z, pupil moves up in the image).
    * ``yaw > 0`` turns the gaze toward world +X (pupil moves right in the image).

    The eye bones point along world +Z, so bone-local X is world X (pitch axis),
    bone-local Y is world Z (yaw axis) and bone-local Z is the gaze axis itself.
    Rotating about local Z would only twist the eye about its line of sight, so
    it is never used. XYZ Euler applies pitch first, then yaw about the vertical.
    """
    bone = armature.pose.bones[f"EyeBone_{side}"]
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = (-pitch, yaw, 0.0)
    bpy.context.view_layer.update()


def zero_pose(armature: bpy.types.Object) -> None:
    """Zero both bone rotations: parallel, straight-ahead gaze.

    This equals the calibrated neutral (both eyes straight ahead), but tests
    that need the calibrated pose should call ``calibration.reset()``.
    """
    for side in EYE_CENTERS:
        set_eye_rotation(armature, side, 0.0, 0.0)


def world_eye_center(eye: bpy.types.Object) -> Vector:
    """The eyeball object's origin is its physical rotation centre by construction."""
    return eye.matrix_world.translation.copy()


def pupil_centre_local(pupil: bpy.types.Object) -> Vector:
    """Centre of the pupil aperture in the pupil object's own coordinates.

    The pupil landmark is an open cap lying on the iris; its open edge is the
    pupil margin painted in the iris texture, mapped onto the eyeball through
    its UVs when the scene is built. The landmark is the mean of the vertices on
    that boundary (edges used by exactly one face), read from the mesh, so it
    follows the geometry if the scene is rebuilt.
    """
    mesh = pupil.data
    uses: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            uses[key] = uses.get(key, 0) + 1
    rim = sorted({index for key, count in uses.items() if count == 1 for index in key})
    if len(rim) < 3:
        raise PupilLandmarkError(f"{pupil.name} has no open margin to define the pupil centre")
    centre = Vector((0.0, 0.0, 0.0))
    for index in rim:
        centre += mesh.vertices[index].co
    return centre / len(rim)


def pupil_centre_world(side: str) -> Vector:
    """World position of the centre of the posed pupil's aperture."""
    pupil = bpy.data.objects[f"Pupil_{side}"]
    return pupil.matrix_world @ pupil_centre_local(pupil)
