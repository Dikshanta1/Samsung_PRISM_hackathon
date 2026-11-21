"""Blender-runtime pupil-mask render: an independent, pixel-exact check of the 2D pupil ground truth.

On the photoreal head the pupil is a dark disc under a lid shadow with corneal
catchlights on its edge, so finding it by thresholding the RGB frame is
unreliable. Instead, the same posed scene is rendered a second time through the
same locked camera with only the eyeballs visible and their material replaced
by an emission mask: white where the iris texture's pupil is (the UV disc
recorded on each eyeball at build time), black elsewhere. The centroid of that
mask is where the renderer actually draws the textured pupil, which can then be
compared with the analytic projection of the ``Pupil_*`` landmark.

Everything changed for the mask render is restored before returning, and the
.blend file is never saved, so the RGB renders and the locked camera and
lighting are unaffected.
"""
from __future__ import annotations

from pathlib import Path

import bpy
import numpy as np

EYES = ("Eye_L", "Eye_R")
MASK_SAMPLES = 16
MASK_FLOOR = 4.0 / 255.0  # anything dimmer is background, not pupil edge coverage


def _mask_material(name: str, pupil_uv: tuple[float, float], radius_uv: float) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    tree = material.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links
    coords = nodes.new("ShaderNodeTexCoord")
    centred = nodes.new("ShaderNodeVectorMath")
    centred.operation = "SUBTRACT"
    centred.inputs[1].default_value = (pupil_uv[0], pupil_uv[1], 0.0)
    distance = nodes.new("ShaderNodeVectorMath")
    distance.operation = "LENGTH"
    inside = nodes.new("ShaderNodeMath")
    inside.operation = "LESS_THAN"
    inside.inputs[1].default_value = radius_uv
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(coords.outputs["UV"], centred.inputs[0])
    links.new(centred.outputs["Vector"], distance.inputs[0])
    links.new(distance.outputs["Value"], inside.inputs[0])
    links.new(inside.outputs["Value"], emission.inputs["Strength"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def render_pupil_mask(output_path: Path) -> dict[str, list[float]]:
    """Render the pupil mask of the current pose to ``output_path``; return each pupil's mask centroid (px)."""
    output_path = Path(output_path).resolve()
    if output_path.suffix.lower() != ".png":
        raise ValueError(f"Mask output must be a .png file, received {output_path.name!r}")
    scene = bpy.context.scene
    world = scene.world.node_tree.nodes.get("Background") if scene.world and scene.world.node_tree else None
    saved_visibility = {obj.name: obj.hide_render for obj in scene.objects}
    saved_materials = {name: list(bpy.data.objects[name].data.materials) for name in EYES}
    saved = (scene.render.filepath, scene.eevee.taa_render_samples, scene.view_settings.view_transform,
             tuple(world.inputs["Color"].default_value) if world else None, scene.render.dither_intensity)
    temporary: list[bpy.types.Material] = []
    try:
        for obj in scene.objects:
            if obj.type != "CAMERA":
                obj.hide_render = obj.name not in EYES
        for name in EYES:
            eye = bpy.data.objects[name]
            mask = _mask_material(f"PupilMask_{name}", tuple(eye["pupil_uv"]), float(eye["pupil_radius_uv"]))
            temporary.append(mask)
            for index, material in enumerate(eye.data.materials):
                if material is not None and material.name.startswith("Std_Eye_"):
                    eye.data.materials[index] = mask
                else:  # any other surface on the eyeball (none in the current build) is made invisible
                    clear = bpy.data.materials.new(f"Clear_{name}")
                    clear.node_tree.nodes.clear()
                    out = clear.node_tree.nodes.new("ShaderNodeOutputMaterial")
                    clear.node_tree.links.new(clear.node_tree.nodes.new("ShaderNodeBsdfTransparent").outputs["BSDF"], out.inputs["Surface"])
                    temporary.append(clear)
                    eye.data.materials[index] = clear
        if world:
            world.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        scene.view_settings.view_transform = "Standard"
        scene.eevee.taa_render_samples = MASK_SAMPLES
        scene.render.dither_intensity = 0.0  # dither noise on the black background would bias the centroids
        output_path.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
    finally:
        for name, hidden in saved_visibility.items():
            scene.objects[name].hide_render = hidden
        for name, materials in saved_materials.items():
            for index, material in enumerate(materials):
                bpy.data.objects[name].data.materials[index] = material
        for material in temporary:
            bpy.data.materials.remove(material)
        scene.render.filepath, scene.eevee.taa_render_samples, scene.view_settings.view_transform = saved[:3]
        if world:
            world.inputs["Color"].default_value = saved[3]
        scene.render.dither_intensity = saved[4]
        bpy.context.view_layer.update()
    return mask_centroids(output_path)


def mask_centroids(path: Path) -> dict[str, list[float]]:
    """Intensity-weighted centroid of each pupil in a mask image; L is the right half of the image."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(image)
    weight = pixels.reshape(height, width, 4)[::-1, :, :3].mean(axis=2)
    weight[weight < MASK_FLOOR] = 0.0
    rows, columns = np.mgrid[0:height, 0:width]
    result = {}
    for side, half in (("L", columns >= width / 2), ("R", columns < width / 2)):
        w = weight * half
        total = float(w.sum())
        if total < 20.0:
            raise RuntimeError(f"Pupil {side} is not visible in the mask render {path.name}")
        result[side] = [float(((columns + 0.5) * w).sum() / total), float(((rows + 0.5) * w).sum() / total)]
    return result
