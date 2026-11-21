"""Build scene.blend: the textured Character Creator head with an independent two-bone eye rig.

    Blender --background --factory-startup --python blender/build_scene.py -- [render_dir] [--source PATH]

The character comes from ``Hassan+V1.blend`` (see ``character_asset.resolve_source``).
Everything else -- the eye rig, pupil landmarks, fixation target, locked camera
and constant lighting -- is created here, so the scene can be rebuilt exactly.
The result is saved in the calibrated neutral pose with every texture packed.
"""
from __future__ import annotations

from math import degrees, radians
from pathlib import Path
import argparse
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration import NEUTRAL_TARGET, reset as reset_fixation
from camera_setup import create_camera
from character_asset import (
    FACE_RIG_NAME, HEAD_BONE, CharacterAssetError, align_optical_axis, append_character, bake_eye_meshes,
    disable_hair_card_shadows, downscale_off_camera_textures, iris_texture, localise_look_keys, prune_shape_keys, pupil_in_texture, pupil_ring_points, rebuild_materials, resolve_source, sclera_sphere,
)
from eye_rig import (
    CENTRE_TOLERANCE_M, EYE_CENTERS, EYE_MIDPOINT, _parent_to_bone, attach_eye, create_eye_armature,
    create_pupil_landmark, set_eye_rotation,
)
from lighting_setup import create_lighting
from render_frame import render_still


ROOT = Path(__file__).resolve().parents[1]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("render_dir", nargs="?", type=Path, default=ROOT / "renders")
    parser.add_argument("--source", help="Character .blend (default: assets/source/Hassan+V1.blend)")
    parser.add_argument("--output", type=Path, default=ROOT / "scene.blend")
    parser.add_argument("--no-renders", action="store_true", help="Skip the three stage-1 check renders")
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(args)


def clean_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def build_eyes(rig: bpy.types.Object, scene: bpy.types.Scene) -> bpy.types.Object:
    """Bake, measure, place and rig both eyeballs; return the EyeRig armature."""
    meshes = bake_eye_meshes(rig)
    measured = {}
    for side, mesh in meshes.items():
        pupil_uv, pupil_radius_uv = pupil_in_texture(iris_texture(mesh))
        centre, radius, residual = sclera_sphere(mesh, pupil_uv)
        measured[side] = (centre, pupil_uv, pupil_radius_uv)
        print(f"EYE_{side} sclera centre={tuple(round(c, 5) for c in centre)} radius={radius * 1000:.2f}mm "
              f"fit_residual={residual * 1000:.2f}mm pupil_uv={tuple(round(c, 4) for c in pupil_uv)} "
              f"pupil_radius_uv={pupil_radius_uv:.4f}")

    # Move the whole character so the fitted eye midpoint is the design midpoint.
    offset = EYE_MIDPOINT - (measured["L"][0] + measured["R"][0]) / 2
    rig.location += offset
    bpy.context.view_layer.update()
    print(f"CHARACTER_OFFSET {tuple(round(c, 6) for c in offset)} m")

    eye_rig = create_eye_armature()
    for side, mesh in meshes.items():
        centre, pupil_uv, pupil_radius_uv = measured[side]
        mesh.transform(Matrix.Translation(offset))
        centre = centre + offset
        error = (centre - EYE_CENTERS[side]).length
        if error > CENTRE_TOLERANCE_M:
            raise CharacterAssetError(
                f"Eye_{side} centre {tuple(centre)} is {error * 1000:.2f} mm from EYE_CENTERS; update eye_rig.py")
        # Snap to the exact design centre (sub-millimetre), then point the optical axis down -Y.
        mesh.transform(Matrix.Translation(EYE_CENTERS[side] - centre))
        # The optical axis is defined by the same point the measurements use:
        # the mean of the pupil-margin ring (see eye_rig.pupil_centre_local).
        _, ring = pupil_ring_points(mesh, pupil_uv, pupil_radius_uv)
        correction = align_optical_axis(mesh, EYE_CENTERS[side], sum(ring, Vector()) / len(ring))
        print(f"EYE_{side} centre snapped by {error * 1000:.3f} mm; optical axis corrected by {degrees(correction):.2f} deg")
        pupil_centre, ring = pupil_ring_points(mesh, pupil_uv, pupil_radius_uv)
        eye = attach_eye(side, mesh, eye_rig, scene)
        # The pupil disc in texture space: shared by the landmark above and the pupil-mask render.
        eye["pupil_uv"] = (pupil_uv.x, pupil_uv.y)
        eye["pupil_radius_uv"] = pupil_radius_uv
        create_pupil_landmark(side, eye, pupil_centre, ring, scene)

    # The eye rig rides on the character's head bone, so posing the head carries the eyes.
    bpy.context.view_layer.update()
    _parent_to_bone(eye_rig, rig, HEAD_BONE)
    bpy.context.view_layer.update()
    return eye_rig


def build(args: argparse.Namespace) -> None:
    scene = bpy.context.scene
    clean_scene()
    source = resolve_source(args.source)
    print(f"CHARACTER_SOURCE {source}")
    rig = append_character(source, scene)
    rebuilt = rebuild_materials(list(rig.children))
    print(f"MATERIALS_REBUILT {len(rebuilt)}: {', '.join(sorted(rebuilt))}")
    print(f"SHAPE_KEYS_REMOVED {prune_shape_keys(list(rig.children))} (eye and lid keys kept)")
    print(f"HAIR_CARD_SHADOWS_OFF {disable_hair_card_shadows(list(rig.children))}")
    print(f"LOOK_KEYS_LOCALISED {localise_look_keys(list(rig.children), EYE_MIDPOINT.z)} vertex deltas faded")
    eye_rig = build_eyes(rig, scene)

    bpy.ops.object.empty_add(type="SPHERE", location=NEUTRAL_TARGET)
    target = bpy.context.active_object
    target.name = "FixationTarget"
    target.empty_display_size = 0.01
    create_camera(scene)
    create_lighting(scene)

    reset_fixation()
    if not args.no_renders:
        args.render_dir.mkdir(parents=True, exist_ok=True)
        render_still(args.render_dir / "stage1_front.png")
        # One eye at a time, relative to the neutral pose, to show the
        # two bones are independent: the left eye yaws, the right eye pitches.
        reset_fixation()
        neutral_yaw_l = eye_rig.pose.bones["EyeBone_L"].matrix_basis.to_euler("XYZ").y
        set_eye_rotation(eye_rig, "L", 0.0, neutral_yaw_l - radians(18))
        render_still(args.render_dir / "stage1_left_eye_rotation.png")
        reset_fixation()
        neutral_yaw_r = eye_rig.pose.bones["EyeBone_R"].matrix_basis.to_euler("XYZ").y
        set_eye_rotation(eye_rig, "R", radians(18), neutral_yaw_r)
        render_still(args.render_dir / "stage1_right_eye_rotation.png")

    # Save the calibrated neutral pose (both eyes straight ahead), self-contained.
    reset_fixation()
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    print(f"TEXTURES_DOWNSCALED {downscale_off_camera_textures()}")
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True)
    print(f"SCENE_BUILD_OK {args.output.resolve()} rig={FACE_RIG_NAME}")


if __name__ == "__main__":
    build(parse_arguments())
