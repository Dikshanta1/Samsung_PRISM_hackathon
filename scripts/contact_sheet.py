"""Blender-runtime contact-sheet compositor for the ten official PNG frames.

Lays the frames out five to a row, in sequence order, each 640 px wide with its
label underneath. The frames are shown as emission textures under the Standard
view transform, so their colours are not altered.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import bpy


TILE = 1.0  # one frame, in scene units
GAP = 0.06
LABEL_BAND = 0.26  # space under each frame for its label
PIXELS_PER_UNIT = 640
COLUMNS, ROWS = 5, 2
SHEET_WIDTH = COLUMNS * TILE + (COLUMNS + 1) * GAP
SHEET_HEIGHT = ROWS * (TILE + LABEL_BAND) + (ROWS + 1) * GAP


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

    bpy.ops.mesh.primitive_plane_add(size=TILE, location=(x, y, 0.0))
    tile = bpy.context.active_object
    tile.data.materials.append(material)

    bpy.ops.object.text_add(location=(x, y - TILE / 2 - LABEL_BAND / 2, 0.01))
    text = bpy.context.active_object
    text.data.body = label.replace(" | ", "\n")  # " | " separates the two label lines
    text.data.align_x = "CENTER"
    text.data.align_y = "CENTER"
    text.data.size = 0.075
    text.data.space_line = 1.15
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
        column, row = index % COLUMNS, index // COLUMNS
        x = -SHEET_WIDTH / 2 + GAP + TILE / 2 + column * (TILE + GAP)
        y = SHEET_HEIGHT / 2 - GAP - TILE / 2 - row * (TILE + LABEL_BAND + GAP)
        add_tile(path, label, x, y)

    bpy.ops.object.camera_add(location=(0.0, 0.0, 10.0))
    camera = bpy.context.active_object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = SHEET_WIDTH  # the sheet is wider than tall, so this spans its width
    camera.rotation_euler = (0.0, 0.0, 0.0)
    # Default camera looks -Z, so it already looks at the XY tile plane.
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = round(SHEET_WIDTH * PIXELS_PER_UNIT)
    scene.render.resolution_y = round(SHEET_HEIGHT * PIXELS_PER_UNIT)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_stamp = False
    scene.view_settings.view_transform = "Standard"  # show the frames' own colours
    scene.view_settings.look = "None"
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
