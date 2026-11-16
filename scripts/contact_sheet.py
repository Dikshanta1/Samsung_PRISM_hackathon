"""Blender-runtime contact-sheet compositor for the ten official PNG frames."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import bpy


def add_tile(image_path: Path, label: str, x: float, y: float) -> None:
    image = bpy.data.images.load(str(image_path), check_existing=False)
    material = bpy.data.materials.new(f"Tile_{image_path.stem}")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    shader_output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    links.new(texture.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], shader_output.inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(x, y + 0.08, 0.0))
    tile = bpy.context.active_object
    tile.scale = (0.52, 0.52, 1.0)
    tile.data.materials.append(material)

    bpy.ops.object.text_add(location=(x, y - 0.50, 0.01))
    text = bpy.context.active_object
    text.data.body = label
    text.data.align_x = "CENTER"
    text.data.align_y = "CENTER"
    text.data.size = 0.13
    text.data.extrude = 0.0
    text.data.materials.append(bpy.data.materials["ContactSheetLabel"])


def build(frame_paths: list[Path], labels: list[str], output: Path) -> None:
    if len(frame_paths) != 10 or len(labels) != 10:
        raise ValueError("Contact sheet requires exactly ten frames and labels")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    label_material = bpy.data.materials.new("ContactSheetLabel")
    label_material.diffuse_color = (0.92, 0.92, 0.92, 1.0)
    label_material.use_nodes = True
    nodes, links = label_material.node_tree.nodes, label_material.node_tree.links
    nodes.clear()
    label_shader_output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.92, 0.92, 0.92, 1.0)
    links.new(emission.outputs["Emission"], label_shader_output.inputs["Surface"])

    for index, (path, label) in enumerate(zip(frame_paths, labels)):
        if not path.is_file():
            raise FileNotFoundError(path)
        column, row = index % 5, index // 5
        add_tile(path, label, (column - 2) * 1.16, 0.70 - row * 1.25)

    bpy.ops.object.camera_add(location=(0.0, 0.0, 10.0))
    camera = bpy.context.active_object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 6.1
    camera.rotation_euler = (0.0, 0.0, 0.0)
    # Default camera looks -Z, so it already looks at the XY tile plane.
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 2500
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("ContactSheetWorld")
    scene.world.color = (0.035, 0.035, 0.035)
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"Contact sheet was not written: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", action="append", type=Path, required=True)
    parser.add_argument("--label", action="append", required=True)
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(arguments)
    build(args.frame, args.label, args.output.resolve())
    print(f"CONTACT_SHEET_OK={args.output.resolve()}")


if __name__ == "__main__":
    main()
