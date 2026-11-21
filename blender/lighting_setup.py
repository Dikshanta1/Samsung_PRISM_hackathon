"""Blender-runtime constant lighting and shading configuration for Track 1.

Every render uses the same two area lights, the same uniform world colour, the
same render engine settings and the same colour management. Nothing here
depends on the eye pose, so lighting is identical across all frames;
``lighting_state`` exposes the full configuration so that this can be checked
before and after each render.
"""
from __future__ import annotations

from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_rig import EYE_MIDPOINT

RENDER_ENGINE = "BLENDER_EEVEE"
RENDER_SAMPLES = 64
VIEW_TRANSFORM = "Standard"
WORLD_COLOR = (0.025, 0.025, 0.025)
WORLD_STRENGTH = 1.0
# Lights are placed relative to the eye midpoint so they follow the face, not the world origin.
LIGHT_AIM_POINT_M = EYE_MIDPOINT + Vector((0.0, 0.0, -0.02))

# name, world location (m), power (W), disk diameter (m), colour
#
# Both lights sit about 48 degrees off the camera axis. A light's reflection on
# the eye (the catchlight) appears about half that angle from the corneal apex,
# about 7 mm, and a 0.20 m disc makes it about 1.4 mm in radius. With at most
# 8.1 degrees of gaze (2.5 mm of pupil travel, plus a 2.4 mm pupil radius) the
# catchlights never fall on the pupil, so the pupil stays fully visible in every
# allowed direction.
LIGHTS = (
    ("KeyLight", EYE_MIDPOINT + Vector((-0.36, -0.42, 0.30)), 5.0, 0.20, (1.0, 1.0, 1.0)),
    ("FillLight", EYE_MIDPOINT + Vector((0.40, -0.36, 0.0)), 2.0, 0.20, (1.0, 1.0, 1.0)),
)


class LightingConfigurationError(RuntimeError):
    """The scene lighting does not match the constant Track 1 configuration."""


def _background_node(world: bpy.types.World) -> bpy.types.Node:
    tree = world.node_tree
    node = next((n for n in tree.nodes if n.type == "BACKGROUND"), None)
    if node is None:
        node = tree.nodes.new("ShaderNodeBackground")
        output = next((n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None) or tree.nodes.new("ShaderNodeOutputWorld")
        tree.links.new(node.outputs["Background"], output.inputs["Surface"])
    return node


def configure_shading(scene: bpy.types.Scene) -> None:
    """Fix the render engine, sampling, world and colour management."""
    scene.render.engine = RENDER_ENGINE
    scene.eevee.taa_render_samples = RENDER_SAMPLES
    scene.eevee.use_shadows = True
    scene.frame_set(1)

    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    if scene.world.node_tree is None:
        scene.world.use_nodes = True
    background = _background_node(scene.world)
    background.inputs["Color"].default_value = (*WORLD_COLOR, 1.0)
    background.inputs["Strength"].default_value = WORLD_STRENGTH

    scene.display_settings.display_device = "sRGB"
    scene.view_settings.view_transform = VIEW_TRANSFORM
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def create_lighting(scene: bpy.types.Scene) -> list[bpy.types.Object]:
    """Create the fixed key and fill lights and apply the shading configuration."""
    lamps = []
    for name, location, power, size, color in LIGHTS:
        data = bpy.data.lights.new(name, type="AREA")
        data.shape = "DISK"
        data.size = size
        data.energy = power
        data.color = color
        lamp = bpy.data.objects.new(name, data)
        scene.collection.objects.link(lamp)
        lamp.location = location
        lamp.rotation_mode = "XYZ"
        lamp.rotation_euler = (LIGHT_AIM_POINT_M - location).to_track_quat("-Z", "Y").to_euler("XYZ")
        lamp.lock_location = (True, True, True)
        lamp.lock_rotation = (True, True, True)
        lamp.lock_scale = (True, True, True)
        lamps.append(lamp)
    configure_shading(scene)
    bpy.context.view_layer.update()
    return lamps


def lighting_state(scene: bpy.types.Scene) -> dict[str, object]:
    """Everything that affects illumination and tone, as plain values for exact comparison."""
    lights = {}
    for obj in sorted(scene.objects, key=lambda o: o.name):
        if obj.type != "LIGHT":
            continue
        data = obj.data
        lights[obj.name] = {
            "matrix_world": [list(row) for row in obj.matrix_world],
            "type": data.type,
            "shape": getattr(data, "shape", None),
            "size_m": getattr(data, "size", None),
            "power_w": data.energy,
            "color": list(data.color),
            "hidden": obj.hide_render,
        }
    background = _background_node(scene.world) if scene.world and scene.world.node_tree else None
    view = scene.view_settings
    return {
        "engine": scene.render.engine,
        "samples": scene.eevee.taa_render_samples,
        "shadows": scene.eevee.use_shadows,
        "frame": scene.frame_current,
        "lights": lights,
        "world_color": list(background.inputs["Color"].default_value) if background else None,
        "world_strength": background.inputs["Strength"].default_value if background else None,
        "display_device": scene.display_settings.display_device,
        "view_transform": view.view_transform,
        "look": view.look,
        "exposure": view.exposure,
        "gamma": view.gamma,
    }


def verify_lighting(scene: bpy.types.Scene) -> None:
    """Raise ``LightingConfigurationError`` listing every deviation from the fixed setup."""
    state = lighting_state(scene)
    problems: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            problems.append(f"{label} is {actual!r}, expected {wanted!r}")

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= 1e-6

    expect("render engine", state["engine"], RENDER_ENGINE)
    expect("render samples", state["samples"], RENDER_SAMPLES)
    expect("view transform", state["view_transform"], VIEW_TRANSFORM)
    expect("look", state["look"], "None")
    expect("light names", sorted(state["lights"]), sorted(name for name, *_ in LIGHTS))
    if not (close(state["exposure"], 0.0) and close(state["gamma"], 1.0)):
        problems.append(f"exposure/gamma are {state['exposure']}/{state['gamma']}, expected 0/1")
    if state["world_color"] is None or not all(close(a, b) for a, b in zip(state["world_color"], WORLD_COLOR)):
        problems.append(f"world colour is {state['world_color']}, expected {WORLD_COLOR}")
    for name, location, power, size, color in LIGHTS:
        light = state["lights"].get(name)
        if light is None:
            continue
        actual_location = Vector([row[3] for row in light["matrix_world"][:3]])
        if (actual_location - location).length > 1e-6:
            problems.append(f"{name} is at {tuple(actual_location)}, expected {tuple(location)}")
        if not close(light["power_w"], power) or not close(light["size_m"], size):
            problems.append(f"{name} power/size are {light['power_w']}/{light['size_m']}, expected {power}/{size}")
        if not all(close(a, b) for a, b in zip(light["color"], color)) or light["hidden"]:
            problems.append(f"{name} colour or visibility changed")
    if problems:
        raise LightingConfigurationError("Lighting is not in the constant Track 1 configuration: " + "; ".join(problems))
