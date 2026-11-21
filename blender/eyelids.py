"""Eyelid follow: the lids track vertical and horizontal gaze, as real lids do.

Character Creator ships ARKit-style "eye look" shape keys on every mesh around
the eye (skin and lashes, eye occlusion, tear line, brows, beard cards). In the
source file their drivers are missing, so this module sets the same value on
every mesh that has the key, keeping lids, lashes and the occlusion shadow
together.

Only the lids move. The eyeballs are rigid and driven by ``EyeBone_*``, so the
ground truth (rotations, pupil centres) is unaffected by anything here.
"""
from __future__ import annotations

from math import atan2, degrees, hypot

import bpy
from mathutils import Vector

# A key value of 1.0 corresponds to this gaze angle. Character Creator's own
# eye-look expressions reach full strength at roughly 25 degrees; the Track 1
# range is about +-8 degrees, so the lids move by about a third of a full look.
FULL_LOOK_DEGREES = 25.0

# Key names per (side, direction). "Left"/"Right" are the subject's own sides,
# matching Eye_L / Eye_R. "In" turns toward the nose, "Out" toward the ear.
LOOK_KEYS = {
    ("L", "up"): "A06_Eye_Look_Up_Left",
    ("R", "up"): "A07_Eye_Look_Up_Right",
    ("L", "down"): "A08_Eye_Look_Down_Left",
    ("R", "down"): "A09_Eye_Look_Down_Right",
    ("L", "out"): "A10_Eye_Look_Out_Left",
    ("L", "in"): "A11_Eye_Look_In_Left",
    ("R", "in"): "A12_Eye_Look_In_Right",
    ("R", "out"): "A13_Eye_Look_Out_Right",
}


def gaze_angles_degrees(direction: Vector) -> tuple[float, float]:
    """(yaw toward world +X, pitch up) of a gaze direction, for a face looking along -Y."""
    return degrees(atan2(direction.x, -direction.y)), degrees(atan2(direction.z, hypot(direction.x, direction.y)))


def key_values(side: str, direction: Vector) -> dict[str, float]:
    """Shape-key values for one eye looking along ``direction``."""
    yaw, pitch = gaze_angles_degrees(direction)
    # The subject's left eye sits at +X, so turning toward +X is outward for L and inward for R.
    toward_plus_x, toward_minus_x = ("out", "in") if side == "L" else ("in", "out")
    amount = {
        "up": max(0.0, pitch), "down": max(0.0, -pitch),
        toward_plus_x: max(0.0, yaw), toward_minus_x: max(0.0, -yaw),
    }
    return {LOOK_KEYS[(side, name)]: min(1.0, value / FULL_LOOK_DEGREES) for name, value in amount.items()}


def lid_meshes() -> list[bpy.types.Object]:
    names = set(LOOK_KEYS.values())
    return [obj for obj in bpy.data.objects
            if obj.type == "MESH" and obj.data.shape_keys and names & set(obj.data.shape_keys.key_blocks.keys())]


def apply(directions: dict[str, Vector]) -> dict[str, float]:
    """Set the lid keys for both eyes from their gaze directions; return the values written."""
    values: dict[str, float] = {}
    for side, direction in directions.items():
        values.update(key_values(side, direction))
    for obj in lid_meshes():
        blocks = obj.data.shape_keys.key_blocks
        for name, value in values.items():
            if name in blocks:
                blocks[name].value = value
    return values
