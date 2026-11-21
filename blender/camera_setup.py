"""Blender-runtime camera configuration, locking and calibration for Track 1.

All lengths are metres. The camera is a pinhole placed ``CAMERA_DISTANCE_M``
(0.400 m) forward of the *eye midpoint* -- the midpoint of the two eyeball
rotation centres -- along the face's forward axis (world -Y), looking straight
back at that midpoint. This is a different quantity from the 0.350 m fixation
target distance, which is measured from the same midpoint but belongs to the
gaze model in ``calibration.py``.

Calibration values are never typed in: the intrinsic matrix, rotation,
translation and projection matrix are derived from the camera object and render
settings that are actually in the scene.

Image coordinate convention (used by every function here):
    * ``u`` grows to the right, ``v`` grows downward, in pixels.
    * ``(0, 0)`` is the top-left *corner* of the top-left pixel, so the centre
      of pixel ``(column, row)`` is ``(column + 0.5, row + 0.5)`` and the image
      centre of a 1024 x 1024 render is ``(512, 512)``.
Camera coordinate convention for ``R`` and ``t`` (computer-vision style):
    * ``+X`` right, ``+Y`` down, ``+Z`` forward along the optical axis.
    * ``x_cam = R @ x_world + t`` and ``[u, v, 1]^T ~ K @ x_cam``.
Blender's own camera frame is ``+X`` right, ``+Y`` up, ``-Z`` forward; the two
differ by ``diag(1, -1, -1)``.
"""
from __future__ import annotations

from math import degrees
from pathlib import Path
import argparse
import json
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration import CAMERA_DISTANCE_M, FACE_FORWARD_WORLD, eye_midpoint
from eye_rig import PupilLandmarkError, pupil_centre_local, pupil_centre_world  # re-exported

CAMERA_NAME = "Camera"
RESOLUTION_PX = 1024
LENS_MM = 70.0
SENSOR_WIDTH_MM = 36.0
SENSOR_HEIGHT_MM = 24.0
SENSOR_FIT = "HORIZONTAL"
CLIP_START_M = 0.01
CLIP_END_M = 10.0

# Blender camera axes (+Y up, -Z forward) to computer-vision axes (+Y down, +Z forward).
BLENDER_TO_CV = Matrix(((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)))

DISTANCE_TOLERANCE_M = 1e-6
AIM_TOLERANCE_DEGREES = 1e-3


class CameraConfigurationError(RuntimeError):
    """The scene camera does not match the locked Track 1 configuration."""


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------

def design_reference_point() -> Vector:
    """Design eye midpoint: the point the 0.400 m distance is measured from."""
    return eye_midpoint()


def measured_reference_point() -> Vector:
    """Eye midpoint measured from the eyeball objects actually in the scene."""
    left = bpy.data.objects["Eye_L"].matrix_world.translation
    right = bpy.data.objects["Eye_R"].matrix_world.translation
    return (left + right) / 2


def design_camera_location() -> Vector:
    return design_reference_point() + CAMERA_DISTANCE_M * FACE_FORWARD_WORLD


def configure_output(scene: bpy.types.Scene) -> None:
    """Fix the image format: 1024 x 1024, square pixels, 8-bit RGB PNG."""
    render = scene.render
    render.resolution_x = RESOLUTION_PX
    render.resolution_y = RESOLUTION_PX
    render.resolution_percentage = 100
    render.pixel_aspect_x = 1.0
    render.pixel_aspect_y = 1.0
    render.use_border = False
    render.film_transparent = False
    render.use_file_extension = True
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGB"
    render.image_settings.color_depth = "8"
    # Blender embeds date, time and render-time text chunks in PNGs by default,
    # which makes two renders of the same pose differ byte for byte.
    for name in dir(render):
        if name.startswith("use_stamp"):
            setattr(render, name, False)


def apply_camera_configuration(camera: bpy.types.Object) -> None:
    """Set the fixed lens, sensor and pose, then lock every transform channel."""
    data = camera.data
    data.type = "PERSP"
    data.lens_unit = "MILLIMETERS"
    data.lens = LENS_MM
    data.sensor_fit = SENSOR_FIT
    data.sensor_width = SENSOR_WIDTH_MM
    data.sensor_height = SENSOR_HEIGHT_MM
    data.shift_x = 0.0
    data.shift_y = 0.0
    data.clip_start = CLIP_START_M
    data.clip_end = CLIP_END_M
    data.dof.use_dof = False

    reference = design_reference_point()
    camera.parent = None
    camera.location = design_camera_location()
    camera.rotation_mode = "XYZ"
    # Blender cameras look along local -Z with local +Y up.
    camera.rotation_euler = (reference - camera.location).to_track_quat("-Z", "Y").to_euler("XYZ")
    camera.scale = (1.0, 1.0, 1.0)
    camera.lock_location = (True, True, True)
    camera.lock_rotation = (True, True, True)
    camera.lock_scale = (True, True, True)


def create_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    """Create the single locked render camera and make it the scene camera."""
    camera = bpy.data.objects.new(CAMERA_NAME, bpy.data.cameras.new(CAMERA_NAME))
    scene.collection.objects.link(camera)
    apply_camera_configuration(camera)
    scene.camera = camera
    configure_output(scene)
    bpy.context.view_layer.update()
    return camera


# --------------------------------------------------------------------------
# State and verification
# --------------------------------------------------------------------------

def scene_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        raise CameraConfigurationError("The scene has no active camera")
    return camera


def camera_state(scene: bpy.types.Scene) -> dict[str, object]:
    """Everything that affects the projection, as plain values for exact comparison."""
    camera = scene_camera(scene)
    data, render = camera.data, scene.render
    return {
        "name": camera.name,
        "matrix_world": [list(row) for row in camera.matrix_world],
        "type": data.type,
        "lens_mm": data.lens,
        "sensor_fit": data.sensor_fit,
        "sensor_width_mm": data.sensor_width,
        "sensor_height_mm": data.sensor_height,
        "shift": [data.shift_x, data.shift_y],
        "clip_m": [data.clip_start, data.clip_end],
        "resolution_px": [render.resolution_x, render.resolution_y],
        "resolution_percentage": render.resolution_percentage,
        "pixel_aspect": [render.pixel_aspect_x, render.pixel_aspect_y],
        "file_format": render.image_settings.file_format,
    }


def verify_camera(scene: bpy.types.Scene) -> None:
    """Raise ``CameraConfigurationError`` listing every deviation from the locked setup."""
    camera = scene_camera(scene)
    data, render = camera.data, scene.render
    problems: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            problems.append(f"{label} is {actual!r}, expected {wanted!r}")

    def expect_close(label: str, actual: float, wanted: float, tolerance: float = 1e-6) -> None:
        if abs(actual - wanted) > tolerance:
            problems.append(f"{label} is {actual!r}, expected {wanted!r}")

    reference = measured_reference_point()
    position = camera.matrix_world.translation
    offset = position - reference
    expect_close("camera distance from eye midpoint (m)", offset.length, CAMERA_DISTANCE_M, DISTANCE_TOLERANCE_M)
    if offset.length > 0 and degrees(offset.angle(FACE_FORWARD_WORLD)) > AIM_TOLERANCE_DEGREES:
        problems.append(f"camera is not straight in front of the face: offset from eye midpoint is {tuple(offset)}")
    optical_axis = camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    aim_error = degrees(optical_axis.angle(reference - position)) if offset.length > 0 else 180.0
    if aim_error > AIM_TOLERANCE_DEGREES:
        problems.append(f"optical axis misses the eye midpoint by {aim_error:.5f} degrees")
    up = camera.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))
    if degrees(up.angle(Vector((0.0, 0.0, 1.0)))) > AIM_TOLERANCE_DEGREES:
        problems.append(f"camera is rolled: image-up is world {tuple(up)}, expected +Z")
    for axis, value in zip("xyz", camera.matrix_world.to_scale()):
        expect_close(f"camera scale {axis}", value, 1.0)

    expect("camera type", data.type, "PERSP")
    expect_close("lens (mm)", data.lens, LENS_MM)
    expect("sensor fit", data.sensor_fit, SENSOR_FIT)
    expect_close("sensor width (mm)", data.sensor_width, SENSOR_WIDTH_MM)
    expect_close("sensor height (mm)", data.sensor_height, SENSOR_HEIGHT_MM)
    expect_close("shift x", data.shift_x, 0.0)
    expect_close("shift y", data.shift_y, 0.0)
    expect("resolution", (render.resolution_x, render.resolution_y), (RESOLUTION_PX, RESOLUTION_PX))
    expect("resolution percentage", render.resolution_percentage, 100)
    expect("pixel aspect", (render.pixel_aspect_x, render.pixel_aspect_y), (1.0, 1.0))
    expect("render border", render.use_border, False)
    expect("file format", render.image_settings.file_format, "PNG")
    expect("location locks", tuple(camera.lock_location), (True, True, True))
    expect("rotation locks", tuple(camera.lock_rotation), (True, True, True))
    expect("scale locks", tuple(camera.lock_scale), (True, True, True))
    if camera.parent is not None:
        problems.append(f"camera is parented to {camera.parent.name}")
    if len(camera.constraints):
        problems.append(f"camera has constraints: {[c.name for c in camera.constraints]}")
    if camera.animation_data is not None or data.animation_data is not None:
        problems.append("camera has animation data")

    if problems:
        raise CameraConfigurationError("Camera is not in the locked Track 1 configuration: " + "; ".join(problems))


# --------------------------------------------------------------------------
# Calibration derived from the actual camera
# --------------------------------------------------------------------------

def image_size(scene: bpy.types.Scene) -> tuple[float, float]:
    scale = scene.render.resolution_percentage / 100.0
    return scene.render.resolution_x * scale, scene.render.resolution_y * scale


def intrinsic_matrix(scene: bpy.types.Scene, camera: bpy.types.Object | None = None) -> Matrix:
    """Pinhole intrinsic matrix ``K`` in pixels, from lens, sensor and resolution.

    ``fx = lens * width / sensor_width`` when the sensor is fitted horizontally
    (``fy = lens * height / sensor_height`` when fitted vertically); the other
    focal length follows from the pixel aspect ratio. Blender's lens shift is
    expressed as a fraction of the fitted image dimension.
    """
    camera = camera or scene_camera(scene)
    data, render = camera.data, scene.render
    if data.type != "PERSP":
        raise CameraConfigurationError(f"Only perspective cameras are calibrated, found {data.type}")
    width, height = image_size(scene)
    aspect_x, aspect_y = render.pixel_aspect_x, render.pixel_aspect_y
    fit = data.sensor_fit
    if fit == "AUTO":
        fit = "HORIZONTAL" if width * aspect_x >= height * aspect_y else "VERTICAL"
    if fit == "HORIZONTAL":
        fx = data.lens * width / data.sensor_width
        fy = fx * aspect_x / aspect_y
        shift_unit_x, shift_unit_y = width, width * aspect_x / aspect_y
    else:
        sensor = data.sensor_height if data.sensor_fit == "VERTICAL" else data.sensor_width
        fy = data.lens * height / sensor
        fx = fy * aspect_y / aspect_x
        shift_unit_x, shift_unit_y = height * aspect_y / aspect_x, height
    cx = width / 2.0 - data.shift_x * shift_unit_x
    cy = height / 2.0 + data.shift_y * shift_unit_y
    return Matrix(((fx, 0.0, cx), (0.0, fy, cy), (0.0, 0.0, 1.0)))


def extrinsics(camera: bpy.types.Object) -> tuple[Matrix, Vector]:
    """World-to-camera rotation ``R`` and translation ``t`` (computer-vision axes)."""
    world_from_camera = camera.matrix_world.to_3x3().normalized()
    rotation = BLENDER_TO_CV @ world_from_camera.transposed()
    translation = -(rotation @ camera.matrix_world.translation)
    return rotation, translation


def projection_matrix(scene: bpy.types.Scene, camera: bpy.types.Object | None = None) -> list[list[float]]:
    """3 x 4 matrix ``P = K [R | t]`` mapping homogeneous world metres to pixels."""
    camera = camera or scene_camera(scene)
    k = intrinsic_matrix(scene, camera)
    rotation, translation = extrinsics(camera)
    kr, kt = k @ rotation, k @ translation
    return [[kr[row][0], kr[row][1], kr[row][2], kt[row]] for row in range(3)]


def project_point(scene: bpy.types.Scene, point: Vector, camera: bpy.types.Object | None = None) -> tuple[float, float, float]:
    """Project a world point to ``(u, v, depth_m)`` using ``P`` alone."""
    p = projection_matrix(scene, camera)
    x, y, z = point
    u, v, w = (row[0] * x + row[1] * y + row[2] * z + row[3] for row in p)
    if w <= 0.0:
        raise ValueError(f"Point {tuple(point)} is behind the camera (depth {w} m)")
    return u / w, v / w, w


def pupil_centres_px(scene: bpy.types.Scene) -> dict[str, list[float]]:
    """Projected 2D centres of the posed pupils, in the image convention above."""
    centres = {}
    for side in ("L", "R"):
        u, v, _ = project_point(scene, pupil_centre_world(side))
        centres[side] = [u, v]
    return centres


def calibration_report(scene: bpy.types.Scene) -> dict[str, object]:
    """Full calibration of the scene camera as JSON-serialisable values."""
    camera = scene_camera(scene)
    k = intrinsic_matrix(scene, camera)
    rotation, translation = extrinsics(camera)
    width, height = image_size(scene)
    reference = measured_reference_point()
    return {
        "units": "metres",
        "reference_point": "eye midpoint: midpoint of the two eyeball rotation centres",
        "reference_point_world_m": list(reference),
        "camera_centre_world_m": list(camera.matrix_world.translation),
        "camera_distance_m": (camera.matrix_world.translation - reference).length,
        "image_size_px": [width, height],
        "lens_mm": camera.data.lens,
        "sensor_mm": [camera.data.sensor_width, camera.data.sensor_height],
        "sensor_fit": camera.data.sensor_fit,
        "image_convention": "u right, v down, origin at top-left corner; pixel centres at +0.5",
        "camera_axes": "+X right, +Y down, +Z forward; x_cam = R x_world + t",
        "intrinsic_matrix_K": [list(row) for row in k],
        "rotation_R": [list(row) for row in rotation],
        "translation_t_m": list(translation),
        "projection_matrix_P": projection_matrix(scene, camera),
        "blender_matrix_world": [list(row) for row in camera.matrix_world],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the scene camera and print its calibration")
    parser.add_argument("--output", type=Path, help="Optional JSON file for the calibration report")
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)
    scene = bpy.context.scene
    verify_camera(scene)
    report = calibration_report(scene)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CAMERA_CALIBRATION " + json.dumps(report))


if __name__ == "__main__":
    main()
