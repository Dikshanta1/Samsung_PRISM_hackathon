"""Blender background acceptance test for the locked camera, calibration and renders.

    Blender --background --factory-startup scene.blend \
        --python-exit-code 1 --python tests/test_camera.py

Nothing is saved to the .blend file. The test writes five renders and their pupil masks to
``renders/stage3_*.png`` and the derived calibration to
``metadata/camera_calibration.json``.
"""
from __future__ import annotations

from pathlib import Path
import json
import random
import struct
import sys
import zlib

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from calibration import CAMERA_DISTANCE_M, TARGET_DISTANCE_M, reset, set_fixation
from camera_setup import (
    LENS_MM, RESOLUTION_PX, SENSOR_WIDTH_MM, CameraConfigurationError, calibration_report, camera_state,
    extrinsics, intrinsic_matrix, measured_reference_point, project_point, projection_matrix, verify_camera,
)
from lighting_setup import LightingConfigurationError, lighting_state, verify_lighting
from pupil_mask import render_pupil_mask
from render_frame import render_still
sys.path.insert(0, str(ROOT))
from metadata.pupil_pixels import pupil_contrast_problem

RENDERS = ROOT / "renders"
METADATA = ROOT / "metadata"
POSES = (
    ("centre", 0.0, 0.0, (0, 0)),
    ("left", -1.0, 0.0, (-1, 0)),
    ("right", 1.0, 0.0, (1, 0)),
    ("up", 0.0, 1.0, (0, -1)),
    ("down", 0.0, -1.0, (0, 1)),
)
MIN_VISIBLE_SHIFT_PX = 10.0  # measured in the rendered image, not predicted
# The head is 1.72 m above the world origin, where one float32 step in Blender's object
# matrices is about 1.2e-7 m. Known points must project to within 1 micrometre of world
# position, i.e. focal * 1e-6 / depth pixels (0.005 px at the eyes, 0.04 px at the target).
KNOWN_POINT_TOLERANCE_M = 1e-6
MAX_PREDICTION_ERROR_PX = 0.25  # pupil drawn in the mask render versus projected pupil centre
MAX_STATIC_DIFFERENCE = 2.0 / 255.0  # regions away from the eyes must not change
# (name, row range, column range) in top-left-origin pixels, all clear of the eyes.
STATIC_REGIONS = (
    ("background", (0, 60), (0, 60)),
    ("forehead", (130, 250), (440, 580)),
    ("mouth", (840, 900), (400, 620)),
    ("chin", (940, 1000), (460, 560)),
)


def scene() -> bpy.types.Scene:
    return bpy.context.scene


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def test_camera_configuration() -> None:
    s = scene()
    verify_camera(s)
    camera = s.camera
    reference = measured_reference_point()
    offset = camera.matrix_world.translation - reference
    assert abs(offset.length - CAMERA_DISTANCE_M) < 1e-6, f"Camera is {offset.length} m from the eye midpoint"
    assert offset.normalized().dot(Vector((0, -1, 0))) > 1 - 1e-9, "Camera is not straight ahead of the face (-Y)"
    forward = camera.matrix_world.to_3x3() @ Vector((0, 0, -1))
    assert forward.dot((reference - camera.matrix_world.translation).normalized()) > 1 - 1e-9, "Camera does not face the eye midpoint"
    target = bpy.data.objects["FixationTarget"].matrix_world.translation
    reset()
    assert abs((target - reference).length - TARGET_DISTANCE_M) < 1e-6, "Fixation target is not 35 cm from the eye midpoint"
    assert abs((camera.matrix_world.translation - target).length - (CAMERA_DISTANCE_M - TARGET_DISTANCE_M)) < 1e-6, \
        "Camera and fixation target distances are confused"
    assert (s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage) == (1024, 1024, 100)
    assert s.render.image_settings.file_format == "PNG"
    assert abs(camera.data.lens - LENS_MM) < 1e-6 and abs(camera.data.sensor_width - SENSOR_WIDTH_MM) < 1e-6
    print("CAMERA_CONFIGURATION_OK")


def test_verification_detects_tampering() -> None:
    """verify_camera / verify_lighting must reject a moved camera, a new lens or a changed light."""
    s = scene()
    camera = s.camera
    original_location, original_rotation, original_lens = camera.location.copy(), camera.rotation_euler.copy(), camera.data.lens

    def rejected(check, error_type) -> bool:
        bpy.context.view_layer.update()
        try:
            check(s)
        except error_type:
            return True
        return False

    camera.location.y -= 0.01
    assert rejected(verify_camera, CameraConfigurationError), "A camera moved 1 cm was accepted"
    camera.location = original_location
    camera.rotation_euler.x += 0.01
    assert rejected(verify_camera, CameraConfigurationError), "A rotated camera was accepted"
    camera.rotation_euler = original_rotation
    camera.data.lens = 50.0
    assert rejected(verify_camera, CameraConfigurationError), "A changed lens was accepted"
    camera.data.lens = original_lens
    s.render.resolution_x = 512
    assert rejected(verify_camera, CameraConfigurationError), "A changed resolution was accepted"
    s.render.resolution_x = RESOLUTION_PX

    light = bpy.data.objects["KeyLight"]
    original_power = light.data.energy
    light.data.energy = original_power * 2
    assert rejected(verify_lighting, LightingConfigurationError), "A changed light power was accepted"
    light.data.energy = original_power

    bpy.context.view_layer.update()
    verify_camera(s)
    verify_lighting(s)
    print("TAMPER_DETECTION_OK")


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def blender_projection_px(camera: bpy.types.Object, point: Vector) -> tuple[float, float]:
    """Project through Blender's own camera projection matrix (independent of K, R, t)."""
    s = scene()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    width = s.render.resolution_x * s.render.resolution_percentage / 100
    height = s.render.resolution_y * s.render.resolution_percentage / 100
    clip = camera.calc_matrix_camera(depsgraph, x=int(width), y=int(height),
                                     scale_x=s.render.pixel_aspect_x, scale_y=s.render.pixel_aspect_y)
    ndc = clip @ camera.matrix_world.inverted() @ point.to_4d()
    return (ndc.x / ndc.w * 0.5 + 0.5) * width, (1.0 - (ndc.y / ndc.w * 0.5 + 0.5)) * height


def view_projection_px(camera: bpy.types.Object, point: Vector) -> tuple[float, float, float]:
    s = scene()
    view = world_to_camera_view(s, camera, point)
    return view.x * s.render.resolution_x, (1.0 - view.y) * s.render.resolution_y, view.z


def test_intrinsics_and_extrinsics() -> None:
    s = scene()
    camera = s.camera
    k = intrinsic_matrix(s)
    # Pinhole focal length in pixels from the camera's own lens and sensor.
    expected_f = camera.data.lens * s.render.resolution_x / camera.data.sensor_width
    assert abs(k[0][0] - expected_f) < 1e-4 and abs(k[1][1] - expected_f) < 1e-4, f"Focal length {k[0][0]}, {k[1][1]} != {expected_f}"
    assert abs(k[0][2] - 512.0) < 1e-6 and abs(k[1][2] - 512.0) < 1e-6, "Principal point is not the image centre"
    assert k[0][1] == 0.0 and k[1][0] == 0.0 and tuple(k[2]) == (0.0, 0.0, 1.0), "K is not an upper-triangular pinhole matrix"

    # K must agree with Blender's own (OpenGL-style) projection matrix.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    clip = camera.calc_matrix_camera(depsgraph, x=RESOLUTION_PX, y=RESOLUTION_PX)
    assert abs(clip[0][0] * RESOLUTION_PX / 2 - k[0][0]) < 1e-3, "fx disagrees with Blender's projection matrix"
    assert abs(clip[1][1] * RESOLUTION_PX / 2 - k[1][1]) < 1e-3, "fy disagrees with Blender's projection matrix"
    assert abs(RESOLUTION_PX / 2 * (1 - clip[0][2]) - k[0][2]) < 1e-3, "cx disagrees with Blender's projection matrix"
    assert abs(RESOLUTION_PX / 2 * (1 + clip[1][2]) - k[1][2]) < 1e-3, "cy disagrees with Blender's projection matrix"

    rotation, translation = extrinsics(camera)
    identity_error = max(abs((rotation @ rotation.transposed())[i][j] - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))
    assert identity_error < 1e-6, "R is not orthonormal"
    assert abs(rotation.determinant() - 1.0) < 1e-6, "R is not a proper rotation"
    centre = -(rotation.transposed() @ translation)
    assert (centre - camera.matrix_world.translation).length < 1e-6, "-R^T t is not the camera centre"
    # Camera +X is world +X, camera +Y (down) is world -Z, camera +Z (forward) is world +Y.
    for row, axis in zip(rotation, (Vector((1, 0, 0)), Vector((0, 0, -1)), Vector((0, 1, 0)))):
        assert (Vector(row) - axis).length < 1e-6, f"Unexpected camera axis {tuple(row)}, expected {tuple(axis)}"
    print(f"INTRINSICS_EXTRINSICS_OK fx={k[0][0]:.4f} fy={k[1][1]:.4f} cx={k[0][2]:.2f} cy={k[1][2]:.2f}")


def test_known_points() -> None:
    """Hand-computed pinhole projections of points whose position is known by construction."""
    s = scene()
    camera = s.camera
    focal = camera.data.lens * s.render.resolution_x / camera.data.sensor_width
    reference = measured_reference_point()
    cases = []
    # (label, world point, lateral offset X, upward offset Z, depth)
    for label, dx, dy, dz in (
        ("eye midpoint", 0.0, 0.0, 0.0),
        ("fixation target", 0.0, -TARGET_DISTANCE_M, 0.0),
        ("5 cm right of midpoint", 0.05, 0.0, 0.0),
        ("5 cm above midpoint", 0.0, 0.0, 0.05),
        ("3 cm left, 2 cm below, 10 cm nearer", -0.03, -0.10, -0.02),
    ):
        cases.append((label, reference + Vector((dx, dy, dz)), dx, dz, CAMERA_DISTANCE_M + dy))
    for side in ("L", "R"):
        centre = bpy.data.objects[f"Eye_{side}"].matrix_world.translation.copy()
        cases.append((f"Eye_{side} centre", centre, centre.x - reference.x, centre.z - reference.z, CAMERA_DISTANCE_M))

    for label, point, lateral, upward, depth in cases:
        expected_u = 512.0 + focal * lateral / depth
        expected_v = 512.0 - focal * upward / depth
        u, v, d = project_point(s, point)
        tolerance = focal * KNOWN_POINT_TOLERANCE_M / depth
        assert abs(u - expected_u) < tolerance and abs(v - expected_v) < tolerance, \
            f"{label}: projected to ({u}, {v}), expected ({expected_u}, {expected_v})"
        assert abs(d - depth) < 1e-6, f"{label}: depth {d}, expected {depth}"
        bu, bv, bd = view_projection_px(camera, point)
        assert abs(u - bu) < tolerance and abs(v - bv) < tolerance and abs(d - bd) < 1e-6, f"{label}: disagrees with world_to_camera_view ({bu}, {bv})"
        print(f"KNOWN_POINT {label}: u={u:.3f} v={v:.3f} depth={d:.4f} m")
    u, v, _ = project_point(s, reference)
    tolerance = focal * KNOWN_POINT_TOLERANCE_M / CAMERA_DISTANCE_M
    assert abs(u - 512.0) < tolerance and abs(v - 512.0) < tolerance, \
        f"Eye midpoint projects to ({u}, {v}), not the image centre"
    try:
        project_point(s, camera.matrix_world.translation + Vector((0, -0.1, 0)))
    except ValueError:
        pass
    else:
        raise AssertionError("A point behind the camera was projected")
    print("KNOWN_POINTS_OK")


def test_against_blender_projection() -> None:
    """P = K [R | t] must match both of Blender's projection paths on random points.

    Errors are compared as world distances (pixels * depth / focal), because
    Blender projects in float32 and the head is 1.72 m from the world origin.
    """
    s = scene()
    camera = s.camera
    focal = intrinsic_matrix(s)[0][0]
    reference = measured_reference_point()
    generator = random.Random(2026)
    worst_view = worst_clip = worst_px = 0.0
    for _ in range(500):
        point = reference + Vector((generator.uniform(-0.12, 0.12), generator.uniform(-0.30, 0.20), generator.uniform(-0.12, 0.12)))
        u, v, depth = project_point(s, point)
        bu, bv, bdepth = view_projection_px(camera, point)
        cu, cv = blender_projection_px(camera, point)
        worst_view = max(worst_view, max(abs(u - bu), abs(v - bv)) * depth / focal)
        worst_clip = max(worst_clip, max(abs(u - cu), abs(v - cv)) * depth / focal)
        worst_px = max(worst_px, abs(u - bu), abs(v - bv), abs(u - cu), abs(v - cv))
        assert abs(depth - bdepth) < 1e-6
    assert worst_view < KNOWN_POINT_TOLERANCE_M, f"P differs from world_to_camera_view by {worst_view * 1e6:.3f} um"
    assert worst_clip < KNOWN_POINT_TOLERANCE_M, f"P differs from Blender's projection matrix by {worst_clip * 1e6:.3f} um"
    print(f"BLENDER_PROJECTION_OK points=500 max_error_view_um={worst_view * 1e6:.3f} max_error_matrix_um={worst_clip * 1e6:.3f} "
          f"max_error_px={worst_px:.2e}")


def test_general_camera_model() -> None:
    """The derivation must hold for other lenses, sensor fits, shifts and poses, not just this camera."""
    s = scene()
    generator = random.Random(7)
    data = bpy.data.cameras.new("CalibrationProbe")
    probe = bpy.data.objects.new("CalibrationProbe", data)
    s.collection.objects.link(probe)
    original_resolution = (s.render.resolution_x, s.render.resolution_y)
    worst = 0.0
    try:
        for lens, fit, shift, resolution in (
            (55.0, "AUTO", (0.0, 0.0), (1024, 1024)),
            (28.0, "HORIZONTAL", (0.04, -0.03), (1024, 1024)),
            (70.0, "VERTICAL", (-0.02, 0.05), (1024, 1024)),
            (35.0, "AUTO", (0.03, 0.02), (1280, 720)),
            (35.0, "AUTO", (-0.03, 0.02), (720, 1280)),
        ):
            data.lens, data.sensor_fit, (data.shift_x, data.shift_y) = lens, fit, shift
            s.render.resolution_x, s.render.resolution_y = resolution
            probe.location = (generator.uniform(-0.2, 0.2), -0.6, generator.uniform(-0.1, 0.2))
            probe.rotation_euler = Euler((1.5708 + generator.uniform(-0.2, 0.2), generator.uniform(-0.2, 0.2), generator.uniform(-0.2, 0.2)))
            bpy.context.view_layer.update()
            for _ in range(50):
                point = Vector((generator.uniform(-0.15, 0.15), generator.uniform(-0.2, 0.2), generator.uniform(-0.15, 0.15)))
                u, v, _ = project_point(s, point, probe)
                bu, bv, _ = view_projection_px(probe, point)
                worst = max(worst, abs(u - bu), abs(v - bv))
    finally:
        s.render.resolution_x, s.render.resolution_y = original_resolution
        bpy.data.objects.remove(probe)
        bpy.data.cameras.remove(data)
        bpy.context.view_layer.update()
    assert worst < 5e-3, f"General camera model differs from Blender by {worst} px"
    verify_camera(s)
    print(f"GENERAL_CAMERA_MODEL_OK max_error_px={worst:.2e}")


# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------

def read_png_header(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name}: missing PNG signature"
    length, kind = struct.unpack(">I4s", data[8:16])
    assert kind == b"IHDR" and length == 13, f"{path.name}: first chunk is not IHDR"
    assert zlib.crc32(data[12:29]) == struct.unpack(">I", data[29:33])[0], f"{path.name}: corrupt IHDR checksum"
    width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", data[16:29])
    assert data[-12:-8] == b"\x00\x00\x00\x00" and data[-8:-4] == b"IEND", f"{path.name}: missing IEND chunk"
    return {"width": width, "height": height, "bit_depth": depth, "colour_type": colour, "interlace": interlace}


def load_pixels(path: Path) -> np.ndarray:
    """Rendered image as float RGB, row 0 at the top (matching the image convention)."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        buffer = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(buffer)
    finally:
        bpy.data.images.remove(image)
    return buffer.reshape(height, width, 4)[::-1, :, :3]


def as_rows(pixels: np.ndarray) -> list[bytes]:
    """8-bit RGB rows (top first), as the standard-library pixel checks expect."""
    return [bytes(row) for row in np.clip(np.rint(pixels * 255.0), 0, 255).astype(np.uint8).reshape(pixels.shape[0], -1)]


def test_renders() -> None:
    s = scene()
    reset()
    camera_reference, lighting_reference = camera_state(s), lighting_state(s)
    images, measured, predicted = {}, {}, {}

    for name, h, v, _ in POSES:
        set_fixation(h, v)
        path = RENDERS / f"stage3_{name}.png"
        result = render_still(path)
        assert Path(result["output"]) == path.resolve() and path.is_file(), f"{name}: render not written"
        header = read_png_header(path)
        assert (header["width"], header["height"]) == (1024, 1024), f"{name}: image is {header['width']} x {header['height']}"
        assert header["bit_depth"] == 8 and header["colour_type"] == 2, f"{name}: not an 8-bit RGB PNG ({header})"
        assert camera_state(s) == camera_reference, f"{name}: camera changed"
        assert lighting_state(s) == lighting_reference, f"{name}: lighting changed"
        verify_camera(s)
        verify_lighting(s)
        images[name] = load_pixels(path)
        assert images[name].shape == (1024, 1024, 3)
        predicted[name] = result["pupil_center_2D"]
        # Where the renderer draws the textured pupil: same pose and camera, pupils only.
        measured[name] = render_pupil_mask(RENDERS / f"stage3_{name}_pupil_mask.png")
        assert camera_state(s) == camera_reference and lighting_state(s) == lighting_reference, f"{name}: mask render changed the scene"
        rows = as_rows(images[name])
        for side in ("L", "R"):
            problem = pupil_contrast_problem(rows, predicted[name][side])
            assert problem is None, f"{name}: projected Pupil_{side} {problem} in the photoreal render"
        for side in ("L", "R"):
            du = measured[name][side][0] - predicted[name][side][0]
            dv = measured[name][side][1] - predicted[name][side][1]
            assert (du * du + dv * dv) ** 0.5 < MAX_PREDICTION_ERROR_PX, \
                f"{name}: rendered Pupil_{side} at {measured[name][side]} but calibration predicts {predicted[name][side]}"
        print(f"RENDER {path.name}: 1024x1024 8-bit RGB PNG, {path.stat().st_size} bytes; pupil mask/predicted "
              + " ".join(f"{side}=({measured[name][side][0]:.2f}, {measured[name][side][1]:.2f})/({predicted[name][side][0]:.2f}, {predicted[name][side][1]:.2f})" for side in ("L", "R")))

    # Constant camera and lighting: everything away from the eyes is pixel-identical.
    for name, _, _, _ in POSES[1:]:
        for region, (r0, r1), (c0, c1) in STATIC_REGIONS:
            difference = float(np.abs(images[name][r0:r1, c0:c1] - images["centre"][r0:r1, c0:c1]).max())
            assert difference <= MAX_STATIC_DIFFERENCE, f"{name}: {region} region changed by {difference * 255:.1f}/255"

    # Visible eye movement, measured in the rendered pixels.
    for name, _, _, (du_sign, dv_sign) in POSES[1:]:
        for side in ("L", "R"):
            du = measured[name][side][0] - measured["centre"][side][0]
            dv = measured[name][side][1] - measured["centre"][side][1]
            along = du * du_sign + dv * dv_sign
            across = abs(du) if du_sign == 0 else abs(dv)
            assert along >= MIN_VISIBLE_SHIFT_PX, f"{name}: Pupil_{side} moved only {along:.1f} px in the rendered image"
            assert across < 2.0, f"{name}: Pupil_{side} drifted {across:.1f} px off-axis in the rendered image"
        changed = float(np.abs(images[name] - images["centre"]).max())
        assert changed > 0.2, f"{name}: render is indistinguishable from centre"
        print(f"VISIBLE_SHIFT {name}: L=({measured[name]['L'][0] - measured['centre']['L'][0]:+.1f}, {measured[name]['L'][1] - measured['centre']['L'][1]:+.1f}) px "
              f"R=({measured[name]['R'][0] - measured['centre']['R'][0]:+.1f}, {measured[name]['R'][1] - measured['centre']['R'][1]:+.1f}) px")

    try:
        render_still(RENDERS / "stage3_bad.jpg")
    except RuntimeError:
        pass
    else:
        raise AssertionError("A non-PNG output path was accepted")
    reset()
    print("RENDERS_OK centre=true left=true right=true up=true down=true camera_fixed=true lighting_constant=true")


def main() -> None:
    test_camera_configuration()
    test_verification_detects_tampering()
    test_intrinsics_and_extrinsics()
    test_known_points()
    test_against_blender_projection()
    test_general_camera_model()
    report = calibration_report(scene())
    assert report["projection_matrix_P"] == projection_matrix(scene())
    METADATA.mkdir(parents=True, exist_ok=True)
    (METADATA / "camera_calibration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    test_renders()
    print("CAMERA_TEST_OK")


if __name__ == "__main__":
    main()
