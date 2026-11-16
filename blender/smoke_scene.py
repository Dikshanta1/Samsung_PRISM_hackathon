"""Minimal, real Blender scene used to validate headless rendering."""

from pathlib import Path
import sys

import bpy


def output_path() -> Path:
    """Read the path supplied after Blender's `--` separator."""
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(arguments) != 1:
        raise ValueError("Usage: blender --background --python smoke_scene.py -- OUTPUT.png")
    return Path(arguments[0]).expanduser().resolve()


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def build_scene() -> None:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=(0, 0, 0))
    sphere = bpy.context.active_object
    sphere.name = "SmokeTestSphere"

    material = bpy.data.materials.new("SmokeTestMaterial")
    material.diffuse_color = (0.08, 0.35, 0.8, 1.0)
    sphere.data.materials.append(material)

    bpy.ops.object.light_add(type="AREA", location=(3, -4, 4))
    light = bpy.context.active_object
    light.name = "SmokeTestKeyLight"
    light.data.energy = 1000
    light.data.shape = "DISK"
    light.data.size = 5

    bpy.ops.object.camera_add(location=(0, -6, 0))
    camera = bpy.context.active_object
    camera.name = "SmokeTestCamera"
    camera.data.lens = 50
    camera.rotation_euler = (sphere.location - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera


def configure_render(destination: Path) -> None:
    scene = bpy.context.scene
    # Workbench is CPU-safe in this headless macOS environment; it still
    # exercises scene creation, camera placement, and Blender PNG output.
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(destination)
    scene.world.color = (0.04, 0.04, 0.04)


def main() -> None:
    destination = output_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    reset_scene()
    build_scene()
    configure_render(destination)
    bpy.ops.wm.save_as_mainfile(filepath=str(destination.with_suffix(".blend")))
    bpy.ops.render.render(write_still=True)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"Render did not create PNG: {destination}")
    print(f"SMOKE_RENDER_OK={destination}")


if __name__ == "__main__":
    main()
