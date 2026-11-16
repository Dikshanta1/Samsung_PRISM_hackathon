"""Create the Stage 1 procedural fallback face and two-bone eye rig."""

from __future__ import annotations

from math import radians
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration import CAMERA_DISTANCE_M, NEUTRAL_TARGET, eye_midpoint, reset as reset_fixation
from eye_rig import EYE_CENTERS, create_eye_armature, create_eye_geometry, set_eye_rotation, zero_pose


ROOT = Path(__file__).resolve().parents[1]


def parse_render_directory() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return Path(args[0]).resolve() if args else ROOT / "renders"


def material(name: str, color: tuple[float, float, float, float], metallic: float = 0.0, roughness: float = 0.5) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = color
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Metallic"].default_value = metallic
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
    # Ears, neck, nose and lips make the fallback clearly human rather than a bare sphere.
    add_uv("Ear_L", (-0.178, 0.035, 0.045), (0.032, 0.020, 0.052), skin)
    add_uv("Ear_R", (0.178, 0.035, 0.045), (0.032, 0.020, 0.052), skin)
    add_uv("Neck", (0, 0.075, -0.205), (0.075, 0.070, 0.095), skin)
    add_uv("Nose", (0, -0.145, 0.020), (0.027, 0.036, 0.050), skin)
    add_uv("Mouth", (0, -0.145, -0.070), (0.062, 0.009, 0.017), lip)
    for side, centre in EYE_CENTERS.items():
        add_torus(f"SocketRim_{side}", centre + Vector((0, 0.008, 0)), 0.044, 0.008, socket)
        brow = add_uv(f"Brow_{side}", (centre.x, -0.145, 0.108), (0.058, 0.012, 0.012), dark)
        brow.rotation_euler.y = radians(-8 if side == "L" else 8)


def look_at(obj: bpy.types.Object, point: Vector) -> None:
    obj.rotation_euler = (point - obj.location).to_track_quat("-Z", "Y").to_euler()


def create_camera_and_lighting() -> None:
    # The camera sits exactly 0.400 m forward of the eye midpoint along the
    # face's -Y axis and its optical axis passes through that midpoint, so the
    # midpoint projects to the image centre and the camera matrix is a pure
    # 90-degree rotation about X.
    midpoint = eye_midpoint()
    bpy.ops.object.camera_add(location=midpoint + Vector((0, -CAMERA_DISTANCE_M, 0)))
    camera = bpy.context.active_object
    camera.name = "Camera"
    camera.data.lens = 40
    look_at(camera, midpoint)
    bpy.context.scene.camera = camera

    for location, power, size in (((-0.32, -0.42, 0.38), 700, 0.30), ((0.30, -0.32, 0.16), 350, 0.22)):
        bpy.ops.object.light_add(type="AREA", location=location)
        lamp = bpy.context.active_object
        lamp.data.energy = power
        lamp.data.shape = "DISK"
        lamp.data.size = size
        look_at(lamp, Vector((0, 0, 0.03)))


def configure_render(path: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.display.shading.light = "STUDIO"
    scene.display.shading.studio_light = "paint.sl"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.world.color = (0.025, 0.025, 0.025)
    scene.render.filepath = str(path)


def render(path: Path) -> None:
    configure_render(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing render: {path}")


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.armatures):
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
    pupil = material("Pupil", (0.003, 0.003, 0.004, 1), roughness=0.20)
    create_head(skin, socket, lip, dark)
    rig = create_eye_armature()
    for side in EYE_CENTERS:
        create_eye_geometry(side, rig, sclera, iris, pupil)
    bpy.ops.object.empty_add(type="SPHERE", location=NEUTRAL_TARGET)
    bpy.context.active_object.name = "FixationTarget"
    bpy.context.active_object.empty_display_size = 0.025
    create_camera_and_lighting()
    # Neutral means "both eyes fixating the neutral target", not zero rotation.
    reset_fixation()
    render(render_dir / "stage1_front.png")
    # Each test poses only one bone from the parallel zero pose; the other stays
    # at zero. One render exercises yaw and the other pitch, so both axes are
    # visibly covered (pitch > 0 looks up, yaw > 0 looks toward image-right).
    zero_pose(rig)
    set_eye_rotation(rig, "L", 0.0, radians(18))
    render(render_dir / "stage1_left_eye_rotation.png")
    zero_pose(rig)
    set_eye_rotation(rig, "R", radians(18), 0.0)
    render(render_dir / "stage1_right_eye_rotation.png")
    # Save the scene in the calibrated, converged neutral pose.
    reset_fixation()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "blender" / "scene.blend"))
    print("SCENE_BUILD_OK")


if __name__ == "__main__":
    build(parse_render_directory())
