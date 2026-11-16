"""Blender background acceptance test for absolute binocular fixation."""
from __future__ import annotations
from pathlib import Path
import sys
import bpy
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from calibration import CAMERA_DISTANCE_M, TARGET_DISTANCE_M, actual_eye_center, angular_error_degrees, convergence, reset, set_fixation
RENDERS = ROOT / "renders"
EPSILON_DEGREES = 0.001
MAX_RAY_MISS_M = 1e-5  # the two gaze rays must pass within 0.01 mm of each other
MAX_VERGENCE_POINT_ERROR_M = 1e-4  # and meet within 0.1 mm of the fixation target
MIN_SHIFT = 10.0 / 1024.0  # a full-scale input must move the pupil at least 10 px
MAX_CROSS_SHIFT = 1.0 / 1024.0  # and no more than 1 px along the other image axis

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
        x, y = pupil_screen_xy(side)
        x0, y0 = neutral[side]
        if h < 0: assert x0 - x > MIN_SHIFT, f"{name}: {side} pupil did not move visually left"
        if h > 0: assert x - x0 > MIN_SHIFT, f"{name}: {side} pupil did not move visually right"
        if v > 0: assert y - y0 > MIN_SHIFT, f"{name}: {side} pupil did not move visually up"
        if v < 0: assert y0 - y > MIN_SHIFT, f"{name}: {side} pupil did not move visually down"
        if h == 0: assert abs(x - x0) < MAX_CROSS_SHIFT, f"{name}: {side} pupil drifted horizontally"
        if v == 0: assert abs(y - y0) < MAX_CROSS_SHIFT, f"{name}: {side} pupil drifted vertically"
    assert_converged(target, name)
    render(name)

def assert_converged(target, name: str) -> None:
    """Both measured gaze rays must meet each other at the one fixation target."""
    result = convergence(target)
    assert result["ray_miss_m"] < MAX_RAY_MISS_M, f"{name}: gaze rays miss each other by {result['ray_miss_m']} m"
    assert result["vergence_point_error_m"] < MAX_VERGENCE_POINT_ERROR_M, f"{name}: eyes converge {result['vergence_point_error_m']} m from the target"

def assert_calibration() -> None:
    """Target 35 cm and camera 40 cm forward of the eye midpoint, camera aimed at it."""
    midpoint = (actual_eye_center("L") + actual_eye_center("R")) / 2
    target = reset()
    camera = bpy.data.objects["Camera"]
    assert abs((target - midpoint).length - TARGET_DISTANCE_M) < 1e-6, "Neutral target is not 35 cm from the eye midpoint"
    assert abs((camera.matrix_world.translation - midpoint).length - CAMERA_DISTANCE_M) < 1e-6, "Camera is not 40 cm from the eye midpoint"
    centre = world_to_camera_view(bpy.context.scene, camera, midpoint)
    assert abs(centre.x - 0.5) < 1e-5 and abs(centre.y - 0.5) < 1e-5, f"Eye midpoint projects to {tuple(centre)[:2]}, not the image centre"

def assert_rig_offset_is_handled() -> None:
    """Moving the armature must not break fixation or go unnoticed by the error metric."""
    rig = bpy.data.objects["EyeRig"]
    original = rig.matrix_world.copy()
    rig.location.x += 0.01
    rig.rotation_euler.z = 0.1
    bpy.context.view_layer.update()
    try:
        for h, v in ((1.0, 0.0), (-1.0, 1.0)):
            target = set_fixation(h, v)
            for side in ("L", "R"):
                assert angular_error_degrees(side, target) < EPSILON_DEGREES, f"offset rig: {side} gaze error too large"
            assert_converged(target, "offset rig")
    finally:
        rig.matrix_world = original
        bpy.context.view_layer.update()

def main() -> None:
    camera_matrix = bpy.data.objects["Camera"].matrix_world.copy()
    assert_calibration()
    assert_rig_offset_is_handled()
    reset()
    neutral = {side: pupil_screen_xy(side) for side in ("L", "R")}
    centres = {side: bpy.data.objects[f"Eye_{side}"].matrix_world.translation.copy() for side in ("L", "R")}
    for h, v, name in [(-1.0, 0.0, "stage2_left.png"), (1.0, 0.0, "stage2_right.png"), (0.0, 1.0, "stage2_up.png"), (0.0, -1.0, "stage2_down.png")]:
        assert_gaze(h, v, name, neutral, centres)
    target = reset()
    for side in ("L", "R"):
        assert angular_error_degrees(side, target) < EPSILON_DEGREES
        assert (bpy.data.objects[f"Eye_{side}"].matrix_world.translation - centres[side]).length < 1e-7, "Reset: eye centre drifted"
        x, y = pupil_screen_xy(side); x0, y0 = neutral[side]
        assert abs(x - x0) < 1e-9 and abs(y - y0) < 1e-9, "Reset is not exact"
    assert_converged(target, "reset")
    assert bpy.data.objects["Camera"].matrix_world == camera_matrix, "Camera changed during gaze tests"
    render("stage2_reset.png")
    print("DIRECTION_TEST_OK left=true right=true up=true down=true reset=true converged=true calibrated=true")

if __name__ == "__main__":
    main()
