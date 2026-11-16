"""Blender background acceptance test for absolute binocular fixation."""
from __future__ import annotations
from pathlib import Path
import sys
import bpy
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from calibration import actual_gaze_direction, angular_error_degrees, reset, set_fixation
RENDERS = ROOT / "renders"
EPSILON_DEGREES = 0.001

def pupil_screen_xy(side: str) -> tuple[float, float]:
    point = world_to_camera_view(bpy.context.scene, bpy.data.objects["Camera"], bpy.data.objects[f"Pupil_{side}"].matrix_world.translation)
    return point.x, point.y

def render(name: str) -> None:
    bpy.context.scene.render.filepath = str(RENDERS / name)
    bpy.ops.render.render(write_still=True)
    assert (RENDERS / name).is_file(), f"Render missing: {name}"

def assert_gaze(h: float, v: float, name: str, neutral: dict[str, tuple[float, float]], centres: dict[str, object]) -> None:
    target = set_fixation(h, v)
    for side in ("L", "R"):
        assert angular_error_degrees(side, target) < EPSILON_DEGREES, f"{name}: {side} gaze error too large"
        assert (bpy.data.objects[f"Eye_{side}"].matrix_world.translation - centres[side]).length < 1e-7, f"{name}: eye centre drifted"
        expected = (target - bpy.data.objects[f"Eye_{side}"].matrix_world.translation).normalized()
        # Float32 scene transforms make the dot product very slightly below 1.
        assert actual_gaze_direction(side).dot(expected) > 0.999999, f"{name}: {side} does not converge"
        x, y = pupil_screen_xy(side)
        x0, y0 = neutral[side]
        if h < 0: assert x < x0, f"{name}: pupil did not move visually left"
        if h > 0: assert x > x0, f"{name}: pupil did not move visually right"
        if v > 0: assert y > y0, f"{name}: pupil did not move visually up"
        if v < 0: assert y < y0, f"{name}: pupil did not move visually down"
    render(name)

def main() -> None:
    camera_matrix = bpy.data.objects["Camera"].matrix_world.copy()
    reset()
    neutral = {side: pupil_screen_xy(side) for side in ("L", "R")}
    centres = {side: bpy.data.objects[f"Eye_{side}"].matrix_world.translation.copy() for side in ("L", "R")}
    for h, v, name in [(-1.0, 0.0, "stage2_left.png"), (1.0, 0.0, "stage2_right.png"), (0.0, 1.0, "stage2_up.png"), (0.0, -1.0, "stage2_down.png")]:
        assert_gaze(h, v, name, neutral, centres)
    target = reset()
    for side in ("L", "R"):
        assert angular_error_degrees(side, target) < EPSILON_DEGREES
        x, y = pupil_screen_xy(side); x0, y0 = neutral[side]
        assert abs(x - x0) < 1e-9 and abs(y - y0) < 1e-9, "Reset is not exact"
    assert bpy.data.objects["Camera"].matrix_world == camera_matrix, "Camera changed during gaze tests"
    render("stage2_reset.png")
    print("DIRECTION_TEST_OK left=true right=true up=true down=true reset=true")

if __name__ == "__main__":
    main()
