"""Create the Stage 1 procedural fallback face and two-bone eye rig."""

from __future__ import annotations

from math import radians, sqrt
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration import NEUTRAL_TARGET, reset as reset_fixation
from camera_setup import create_camera
from eye_rig import EYE_CENTERS, create_eye_armature, create_eye_geometry, set_eye_rotation, zero_pose
from lighting_setup import create_lighting
from render_frame import render_still


ROOT = Path(__file__).resolve().parents[1]


def parse_render_directory() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return Path(args[0]).resolve() if args else ROOT / "renders"


def material(name: str, color: tuple[float, float, float, float], metallic: float = 0.0, roughness: float = 0.5, specular: float = 0.5) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = color
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Metallic"].default_value = metallic
    node.inputs["Specular IOR Level"].default_value = specular
    return value


def smooth(obj: bpy.types.Object) -> None:
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def add_uv(name: str, location: tuple[float, float, float], scale: tuple[float, float, float], mat: bpy.types.Material) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    smooth(obj)
    return obj


def add_torus(name: str, location: Vector, major: float, minor: float, mat: bpy.types.Material) -> bpy.types.Object:
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=48, minor_segments=12, location=location, rotation=(radians(90), 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(mat)
    smooth(obj)
    return obj


def create_head(skin: bpy.types.Material, socket: bpy.types.Material, lip: bpy.types.Material, dark: bpy.types.Material) -> None:
    head = add_uv("HumanHead", (0, 0.035, 0.035), (0.175, 0.145, 0.235), skin)
    bpy.context.view_layer.update()
    mw = head.matrix_world
    mwi = mw.inverted()
    for vertex in head.data.vertices:
        wco = mw @ vertex.co
        if wco.y > 0.0:
            continue
        for centre in EYE_CENTERS.values():
            dx, dz = wco.x - centre.x, wco.z - centre.z
            r_sq = dx * dx + dz * dz
            if r_sq < 0.043 ** 2:
                target_y = centre.y + sqrt(0.043 ** 2 - r_sq)
                if wco.y < target_y:
                    wco.y = target_y
                    vertex.co = mwi @ wco
    head.data.update()
    # Ears, neck, nose and lips make the fallback clearly human rather than a bare sphere.
    add_uv("Ear_L", (-0.178, 0.035, 0.045), (0.032, 0.020, 0.052), skin)
    add_uv("Ear_R", (0.178, 0.035, 0.045), (0.032, 0.020, 0.052), skin)
    add_uv("Neck", (0, 0.075, -0.205), (0.075, 0.070, 0.095), skin)
    add_uv("Nose", (0, -0.145, 0.015), (0.016, 0.036, 0.048), skin)
    add_uv("Mouth", (0, -0.145, -0.070), (0.062, 0.009, 0.017), lip)
    for side, centre in EYE_CENTERS.items():
        add_torus(f"SocketRim_{side}", centre + Vector((0, 0.009, 0)), 0.0435, 0.0068, socket)
        brow = add_uv(f"Brow_{side}", (centre.x, -0.145, 0.108), (0.058, 0.012, 0.012), dark)
        brow.rotation_euler.y = radians(8 if side == "L" else -8)


def render(path: Path) -> None:
    render_still(path)


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.armatures, bpy.data.cameras, bpy.data.lights):
        for block in datablocks:
            if block.users == 0:
                datablocks.remove(block)


def build(render_dir: Path) -> None:
    render_dir.mkdir(parents=True, exist_ok=True)
    clean_scene()
    skin = material("Skin", (0.52, 0.20, 0.12, 1), roughness=0.62)
    socket = material("SocketSkin", (0.34, 0.10, 0.07, 1), roughness=0.70)
    lip = material("Lip", (0.42, 0.055, 0.055, 1), roughness=0.48)
    dark = material("HairAndBrow", (0.025, 0.012, 0.008, 1), roughness=0.82)
    sclera = material("Sclera", (0.92, 0.92, 0.86, 1), roughness=0.34)
    iris = material("Iris", (0.04, 0.23, 0.16, 1), roughness=0.30)
    pupil = material("Pupil", (0.003, 0.003, 0.004, 1), roughness=0.25, specular=0.04)
    create_head(skin, socket, lip, dark)
    rig = create_eye_armature()
    for side in EYE_CENTERS:
        create_eye_geometry(side, rig, sclera, iris, pupil)
    bpy.ops.object.empty_add(type="SPHERE", location=NEUTRAL_TARGET)
    bpy.context.active_object.name = "FixationTarget"
    bpy.context.active_object.empty_display_size = 0.025
    create_camera(bpy.context.scene)
    create_lighting(bpy.context.scene)
    # Neutral means "both eyes fixating the neutral target", not zero rotation.
    reset_fixation()
    render(render_dir / "stage1_front.png")
    # Each test poses only one bone relative to the neutral front pose while the
    # other eye stays completely fixed. One render exercises yaw and the other
    # pitch, so both axes and single-eye independence are visibly covered.
    reset_fixation()
    neutral_yaw_l = rig.pose.bones["EyeBone_L"].matrix_basis.to_euler("XYZ").y
    set_eye_rotation(rig, "L", 0.0, neutral_yaw_l - radians(18))
    render(render_dir / "stage1_left_eye_rotation.png")
    reset_fixation()
    neutral_yaw_r = rig.pose.bones["EyeBone_R"].matrix_basis.to_euler("XYZ").y
    set_eye_rotation(rig, "R", radians(18), neutral_yaw_r)
    render(render_dir / "stage1_right_eye_rotation.png")
    # Save the scene in the calibrated, converged neutral pose.
    reset_fixation()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "blender" / "scene.blend"))
    print("SCENE_BUILD_OK")


if __name__ == "__main__":
    build(parse_render_directory())
