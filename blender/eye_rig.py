"""Blender-only construction and verification helpers for the two-eye rig."""

from __future__ import annotations

from math import sqrt
import bmesh
from mathutils import Matrix, Vector
import bpy


EYE_CENTERS = {
    "L": Vector((-0.066, -0.133, 0.055)),
    "R": Vector((0.066, -0.133, 0.055)),
}


def _smooth(obj: bpy.types.Object) -> None:
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


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
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    armature = bpy.context.active_object
    armature.name = "EyeRig"
    armature.data.name = "EyeRigData"
    edit_bones = armature.data.edit_bones
    edit_bones.remove(edit_bones[0])

    for side, center in EYE_CENTERS.items():
        bone = edit_bones.new(f"EyeBone_{side}")
        bone.head = center
        bone.tail = center + Vector((0, 0, 0.045))
        bone.use_deform = False

    bpy.ops.object.mode_set(mode="OBJECT")
    armature.show_in_front = True
    return armature


def create_eye_geometry(
    side: str,
    armature: bpy.types.Object,
    sclera_material: bpy.types.Material,
    iris_material: bpy.types.Material,
    pupil_material: bpy.types.Material,
) -> bpy.types.Object:
    """Create a true sclera sphere with iris/pupil meshes parented to it."""
    center = EYE_CENTERS[side]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.037, location=center)
    eye = bpy.context.active_object
    eye.name = f"Eye_{side}"
    eye.data.materials.append(sclera_material)
    _smooth(eye)
    _parent_to_bone(eye, armature, f"EyeBone_{side}")

    # Spherical-cap shells conform to the 37 mm sclera surface without rim overhang,
    # folded edge normals, inter-mesh intersection, or cast drop shadows.
    for label, radius, depth, r_shell, material in (
        ("Iris", 0.019, 0.0020, 0.03730, iris_material),
        ("Pupil", 0.0072, 0.0010, 0.03755, pupil_material),
    ):
        y_origin = sqrt(r_shell * r_shell - radius * radius) - depth
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=48,
            ring_count=24,
            radius=1,
            location=center + Vector((0, -y_origin, 0)),
        )
        feature = bpy.context.active_object
        feature.name = f"{label}_{side}"
        feature.scale = (radius, depth, radius)
        bm = bmesh.new()
        bm.from_mesh(feature.data)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.y > 1e-4], context="VERTS")
        for vertex in bm.verts:
            lx, lz = vertex.co.x, vertex.co.z
            unit_r_sq = min(1.0, lx * lx + lz * lz)
            rho_sq = (radius ** 2) * unit_r_sq
            dy = -sqrt(max(0.0, r_shell * r_shell - rho_sq))
            vertex.co.y = (dy + y_origin) / depth
        bm.to_mesh(feature.data)
        bm.free()
        feature.data.update()
        _smooth(feature)
        feature.visible_shadow = False
        feature.data.materials.append(material)
        feature.parent = eye
        feature.matrix_parent_inverse = eye.matrix_world.inverted()

    return eye


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

    This is the rig's rest pose, not the calibrated neutral. The calibrated
    neutral converges both eyes on the fixation target; use
    ``calibration.reset()`` for that.
    """
    for side in EYE_CENTERS:
        set_eye_rotation(armature, side, 0.0, 0.0)


def world_eye_center(eye: bpy.types.Object) -> Vector:
    """The sphere origin is the physical rotation centre by construction."""
    return eye.matrix_world.translation.copy()
