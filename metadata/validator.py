"""Validate the official ``metadata.json`` and write ``outputs/validation_report.json``.

    python3 metadata/validator.py

Ordinary Python, standard library only. Every check is independent of the code
that produced the metadata:

* schema: ten records, exactly the required keys, finite numbers only;
* sequence: frame = k, theta = 2*pi*k/10, h = sin(theta), v = cos(theta);
* rotations: the XYZ Euler angles are turned back into a gaze direction, which
  must pass through the measured 3D pupil centre and hit the fixation target
  that h and v define;
* pupils: each 2D centre must equal the measured 3D pupil centre projected with
  the record's own camera matrix, and must match the dark pupil found in the
  pixels of that frame's PNG (whose SHA-256 is checked too);
* camera: P must equal K [R | t], K must follow from the lens, sensor and image
  size, R must be a rotation, and the camera must sit 0.400 m from the eye
  midpoint, on its optical axis, identically in every frame.

The report is written whether or not validation passes; ``validate`` then
raises ``MetadataValidationError`` listing every failure.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "metadata.json"
REPORT_PATH = ROOT / "outputs" / "validation_report.json"
PROVENANCE_PATH = ROOT / "metadata" / "official_sequence.json"
RENDERS_DIR = ROOT / "renders"

REQUIRED_KEYS = ("frame", "theta", "input", "eye_rotation_L", "eye_rotation_R",
                 "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix")
FRAME_COUNT = 10
IMAGE_SIZE_PX = 1024
TARGET_DISTANCE_M = 0.350
TARGET_BOUND_M = 0.050
CAMERA_DISTANCE_M = 0.400

FORMULA_TOLERANCE = 1e-12
GAZE_TOLERANCE_DEGREES = 0.01
ROLL_TOLERANCE_DEGREES = 0.01
REPROJECTION_TOLERANCE_PX = 0.01
PIXEL_TOLERANCE_PX = 1.5  # rendered pupil edges are located to about half a pixel
MATRIX_TOLERANCE = 1e-3
DISTANCE_TOLERANCE_M = 1e-5
PUPIL_SEARCH_RADIUS_PX = 52
PUPIL_DARK_LEVEL = 77  # 0.30 of 255


class MetadataValidationError(ValueError):
    """The metadata failed validation; ``errors`` lists every failure."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} metadata validation error(s):\n  " + "\n  ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- small numeric helpers

def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_vector(value: object, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(is_number(item) for item in value)


def is_matrix(value: object, rows: int, columns: int) -> bool:
    return isinstance(value, list) and len(value) == rows and all(is_vector(row, columns) for row in value)


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    length = norm(a)
    return [x / length for x in a]


def angle_degrees(a, b) -> float:
    a, b = unit(a), unit(b)
    cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    return math.degrees(math.atan2(norm(cross), dot(a, b)))


def gaze_from_euler_xyz_degrees(rotation: list[float]) -> list[float]:
    """World gaze direction of an eye whose local line of sight is -Y, for R = Rz Ry Rx."""
    rx, ry, rz = (math.radians(angle) for angle in rotation)
    sx, cx, sy, cy, sz, cz = math.sin(rx), math.cos(rx), math.sin(ry), math.cos(ry), math.sin(rz), math.cos(rz)
    return [-(cz * sy * sx - sz * cx), -(sz * sy * sx + cz * cx), -(cy * sx)]


def project(matrix: list[list[float]], point: list[float]) -> list[float]:
    x, y, w = (dot(row[:3], point) + row[3] for row in matrix)
    return [x / w, y / w]


# ---------------------------------------------------------------- image measurement

def read_png_rows(path: Path, first_row: int, last_row: int) -> dict[int, bytes]:
    """Decode rows of an 8-bit RGB 1024 x 1024 PNG; raises ``ValueError`` if it is not one."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    position, compressed, header, kind = 8, b"", None, b""
    while position + 12 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        if zlib.crc32(kind + body) != int.from_bytes(data[position + 8 + length:position + 12 + length], "big"):
            raise ValueError("corrupt PNG chunk")
        if kind == b"IHDR":
            header = body
        elif kind == b"IDAT":
            compressed += body
        position += 12 + length
    if header is None or kind != b"IEND":
        raise ValueError("truncated PNG")
    size = (int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big"))
    if size != (IMAGE_SIZE_PX, IMAGE_SIZE_PX) or header[8:13] != bytes((8, 2, 0, 0, 0)):
        raise ValueError(f"expected a {IMAGE_SIZE_PX} x {IMAGE_SIZE_PX} 8-bit RGB PNG, found {size[0]} x {size[1]}")
    raw = zlib.decompress(compressed)
    stride = IMAGE_SIZE_PX * 3
    if len(raw) != IMAGE_SIZE_PX * (stride + 1):
        raise ValueError("PNG holds the wrong amount of pixel data")
    rows, previous = {}, bytes(stride)
    for index in range(last_row + 1):
        start = index * (stride + 1)
        filter_type, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if filter_type == 1:
            for i in range(3, stride):
                line[i] = (line[i] + line[i - 3]) & 255
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif filter_type == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - 3] if i >= 3 else 0) + previous[i]) >> 1)) & 255
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - 3] if i >= 3 else 0
                b = previous[i]
                c = previous[i - 3] if i >= 3 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif filter_type != 0:
            raise ValueError(f"unknown PNG filter {filter_type}")
        previous = bytes(line)
        if index >= first_row:
            rows[index] = previous
    return rows


def pupil_in_pixels(rows: dict[int, bytes], around: list[float]) -> list[float] | None:
    """Centre of the dark pupil within the search radius of ``around``, or ``None`` if absent."""
    cu, cv = around
    columns, lines = [], []
    for row in range(int(cv) - PUPIL_SEARCH_RADIUS_PX, int(cv) + PUPIL_SEARCH_RADIUS_PX + 1):
        line = rows.get(row)
        if line is None:
            continue
        for column in range(max(0, int(cu) - PUPIL_SEARCH_RADIUS_PX), min(IMAGE_SIZE_PX, int(cu) + PUPIL_SEARCH_RADIUS_PX + 1)):
            if (column + 0.5 - cu) ** 2 + (row + 0.5 - cv) ** 2 > PUPIL_SEARCH_RADIUS_PX ** 2:
                continue
            if max(line[3 * column:3 * column + 3]) < PUPIL_DARK_LEVEL:
                columns.append(column)
                lines.append(row)
    if len(columns) < 100:
        return None
    return [(min(columns) + max(columns) + 1) / 2, (min(lines) + max(lines) + 1) / 2]


# ---------------------------------------------------------------- checks

def check_schema(records: object, errors: list[str]) -> list[dict]:
    """Structural checks. Returns the records that are sound enough for the numeric checks."""
    if not isinstance(records, list):
        errors.append("metadata must be a JSON array of records")
        return []
    if len(records) != FRAME_COUNT:
        errors.append(f"expected {FRAME_COUNT} records, found {len(records)}")
    usable = []
    for index, record in enumerate(records):
        where = f"record {index}"
        if not isinstance(record, dict):
            errors.append(f"{where}: is not an object")
            continue
        missing = [key for key in REQUIRED_KEYS if key not in record]
        extra = [key for key in record if key not in REQUIRED_KEYS]
        if missing:
            errors.append(f"{where}: missing required field(s) {missing}")
        if extra:
            errors.append(f"{where}: unexpected field(s) {extra}")
        problems = []
        if "frame" in record and (isinstance(record["frame"], bool) or not isinstance(record["frame"], int)):
            problems.append("frame is not an integer")
        if "theta" in record and not is_number(record["theta"]):
            problems.append("theta is not a finite number")
        if "input" in record:
            value = record["input"]
            if not isinstance(value, dict) or sorted(value) != ["h", "v"] or not all(is_number(value[k]) for k in ("h", "v")):
                problems.append("input must be {h, v} with finite numbers")
        for key, length in (("eye_rotation_L", 3), ("eye_rotation_R", 3), ("pupil_center_2D_L", 2), ("pupil_center_2D_R", 2)):
            if key in record and not is_vector(record[key], length):
                problems.append(f"{key} must be {length} finite numbers (no NaN or infinity)")
        if "camera_matrix" in record and not is_matrix(record["camera_matrix"], 3, 4):
            problems.append("camera_matrix must be 3 x 4 finite numbers (no NaN or infinity)")
        errors.extend(f"{where}: {problem}" for problem in problems)
        if not missing and not problems:
            usable.append(record)
    return usable


def check_camera(matrix: list[list[float]], calibration: dict, where: str, errors: list[str]) -> dict:
    """The camera matrix must be the pinhole projection of the calibrated camera."""
    k, rotation, translation = calibration["intrinsic_matrix_K"], calibration["rotation_R"], calibration["translation_t_m"]
    if not (is_matrix(k, 3, 3) and is_matrix(rotation, 3, 3) and is_vector(translation, 3)):
        errors.append(f"{where}: calibration K, R or t is malformed")
        return {}
    width, height = calibration["image_size_px"]
    expected_focal = calibration["lens_mm"] * width / calibration["sensor_mm"][0]
    if (width, height) != (IMAGE_SIZE_PX, IMAGE_SIZE_PX):
        errors.append(f"{where}: image size is {width} x {height}")
    if abs(k[0][0] - expected_focal) > MATRIX_TOLERANCE or abs(k[1][1] - expected_focal) > MATRIX_TOLERANCE:
        errors.append(f"{where}: focal lengths {k[0][0]}, {k[1][1]} px do not follow from the lens and sensor ({expected_focal})")
    if abs(k[0][2] - width / 2) > MATRIX_TOLERANCE or abs(k[1][2] - height / 2) > MATRIX_TOLERANCE:
        errors.append(f"{where}: principal point ({k[0][2]}, {k[1][2]}) is not the image centre")
    if max(abs(k[0][1]), abs(k[1][0]), abs(k[2][0]), abs(k[2][1]), abs(k[2][2] - 1)) > 1e-9:
        errors.append(f"{where}: K is not an upper-triangular pinhole matrix")
    orthogonality = max(abs(dot(rotation[i], rotation[j]) - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))
    determinant = dot(rotation[0], [rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1],
                                    rotation[1][2] * rotation[2][0] - rotation[1][0] * rotation[2][2],
                                    rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0]])
    if orthogonality > 1e-5 or abs(determinant - 1.0) > 1e-5:
        errors.append(f"{where}: R is not a rotation matrix (orthogonality error {orthogonality:.2e}, det {determinant:.6f})")
    composed = [[dot(k[i], [rotation[r][c] for r in range(3)]) for c in range(3)] + [dot(k[i], translation)] for i in range(3)]
    matrix_error = max(abs(composed[i][j] - matrix[i][j]) for i in range(3) for j in range(4))
    if matrix_error > MATRIX_TOLERANCE:
        errors.append(f"{where}: camera_matrix differs from K [R | t] by {matrix_error:.3g}")
    centre = [-dot([rotation[r][c] for r in range(3)], translation) for c in range(3)]
    reference = calibration["reference_point_world_m"]
    distance = norm(sub(centre, reference))
    if abs(distance - CAMERA_DISTANCE_M) > DISTANCE_TOLERANCE_M:
        errors.append(f"{where}: camera is {distance:.6f} m from the eye midpoint, expected {CAMERA_DISTANCE_M}")
    principal = project(matrix, reference)
    if max(abs(principal[0] - width / 2), abs(principal[1] - height / 2)) > REPROJECTION_TOLERANCE_PX:
        errors.append(f"{where}: the eye midpoint projects to {principal}, not the image centre")
    return {"camera_centre_world_m": centre, "camera_distance_m": distance, "focal_length_px": k[0][0],
            "principal_point_px": [k[0][2], k[1][2]], "matrix_vs_K_R_t_max_difference": matrix_error,
            "eye_midpoint_projection_px": principal}


def validate(metadata_path: Path = METADATA_PATH, *, provenance_path: Path = PROVENANCE_PATH,
             renders_dir: Path = RENDERS_DIR, report_path: Path | None = REPORT_PATH) -> dict[str, object]:
    """Validate ``metadata_path``; write the report; raise ``MetadataValidationError`` on any failure."""
    errors: list[str] = []
    frames_report: list[dict] = []
    camera_report: dict = {}
    try:
        # Python's json accepts the non-standard NaN / Infinity tokens unless told otherwise.
        def reject(token: str):
            raise ValueError(f"non-numeric JSON value {token}")
        records = json.loads(metadata_path.read_text(encoding="utf-8"), parse_constant=reject)
    except (OSError, ValueError) as error:
        records = None
        errors.append(f"cannot read {metadata_path.name}: {error}")
    usable = check_schema(records, errors) if records is not None else []

    provenance: dict[int, dict] = {}
    try:
        for measured in json.loads(provenance_path.read_text(encoding="utf-8"))["frames"]:
            provenance[measured["frame"]] = measured
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(f"cannot read Blender measurements {provenance_path.name}: {error}")

    first_matrix = usable[0]["camera_matrix"] if usable else None
    for index, record in enumerate(usable):
        k = record["frame"]
        where = f"frame {k}"
        if k != index:
            errors.append(f"record {index}: frame is {k}, expected {index}")
        if not 0 <= k < FRAME_COUNT:
            continue
        theta = 2.0 * math.pi * k / FRAME_COUNT
        h, v = record["input"]["h"], record["input"]["v"]
        if abs(record["theta"] - theta) > FORMULA_TOLERANCE:
            errors.append(f"{where}: theta is {record['theta']!r}, expected {theta!r}")
        if abs(h - math.sin(theta)) > FORMULA_TOLERANCE or abs(v - math.cos(theta)) > FORMULA_TOLERANCE:
            errors.append(f"{where}: input is h={h!r}, v={v!r}, expected h={math.sin(theta)!r}, v={math.cos(theta)!r}")
        if not (-1.0 <= h <= 1.0 and -1.0 <= v <= 1.0):
            errors.append(f"{where}: input is outside [-1, +1]")
        if record["camera_matrix"] != first_matrix:
            errors.append(f"{where}: camera_matrix differs from frame {usable[0]['frame']}; the camera must be fixed")
        entry: dict = {"frame": k, "theta": record["theta"], "input": {"h": h, "v": v}}
        frames_report.append(entry)

        measured = provenance.get(k)
        if measured is None:
            errors.append(f"{where}: no Blender measurement to verify against")
            continue
        try:
            calibration = measured["camera_calibration"]
            entry["camera"] = check_camera(record["camera_matrix"], calibration, where, errors)
            if k == 0:
                camera_report = dict(entry["camera"], camera_matrix=record["camera_matrix"])
            centres, pupils = measured["eye_center_world_m"], measured["pupil_center_world_m"]
            midpoint = [(a + b) / 2 for a, b in zip(centres["L"], centres["R"])]
            forward = unit(sub(entry["camera"]["camera_centre_world_m"], midpoint))  # the face looks at the camera
            right, up = [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]  # image-right and up, as rows 1 and 2 of R confirm below
            rotation = calibration["rotation_R"]
            if angle_degrees(rotation[0], right) > 0.01 or angle_degrees([-x for x in rotation[1]], up) > 0.01:
                errors.append(f"{where}: camera axes are not image-right = world +X, image-up = world +Z")
            target = [midpoint[i] + TARGET_DISTANCE_M * forward[i] + TARGET_BOUND_M * (h * right[i] + v * up[i]) for i in range(3)]
            entry["fixation_target_world_m"] = target
        except (KeyError, TypeError, IndexError, ZeroDivisionError) as error:
            errors.append(f"{where}: Blender measurement is incomplete ({error!r})")
            continue

        rows = None
        image = renders_dir / f"frame_{k:02d}.png"
        entry["image"] = f"{renders_dir.name}/{image.name}"
        if not image.is_file():
            errors.append(f"{where}: rendered image {image.name} is missing")
        else:
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            entry["image_sha256"] = digest
            if digest != measured.get("image_sha256"):
                errors.append(f"{where}: {image.name} is not the image this record was measured with (SHA-256 differs)")
            try:
                rows = read_png_rows(image, IMAGE_SIZE_PX // 2 - 2 * PUPIL_SEARCH_RADIUS_PX, IMAGE_SIZE_PX // 2 + 2 * PUPIL_SEARCH_RADIUS_PX)
            except (ValueError, zlib.error) as error:
                errors.append(f"{where}: {image.name} is invalid: {error}")

        for side in ("L", "R"):
            rotation_deg = record[f"eye_rotation_{side}"]
            reported = record[f"pupil_center_2D_{side}"]
            centre, pupil = centres[side], pupils[side]
            # Rotation: within range, no roll, and its line of sight passes through the pupil and the target.
            if max(abs(angle) for angle in rotation_deg) > 180.0:
                errors.append(f"{where}: eye_rotation_{side} is outside [-180, 180] degrees")
            if abs(rotation_deg[1]) > ROLL_TOLERANCE_DEGREES:
                errors.append(f"{where}: eye_rotation_{side} has {rotation_deg[1]:.4f} degrees of roll about the line of sight")
            gaze = gaze_from_euler_xyz_degrees(rotation_deg)
            to_pupil = angle_degrees(gaze, sub(pupil, centre))
            to_target = angle_degrees(gaze, sub(target, centre))
            if to_pupil > GAZE_TOLERANCE_DEGREES:
                errors.append(f"{where}: eye_rotation_{side} is {to_pupil:.4f} degrees from the measured pupil axis")
            if to_target > GAZE_TOLERANCE_DEGREES:
                errors.append(f"{where}: eye_rotation_{side} misses the fixation target for this input by {to_target:.4f} degrees")
            # Pupil: inside the image, equal to the projected 3D pupil centre, and not the eyeball centre.
            if not (0.0 <= reported[0] <= IMAGE_SIZE_PX and 0.0 <= reported[1] <= IMAGE_SIZE_PX):
                errors.append(f"{where}: pupil_center_2D_{side} {reported} is outside the image")
            projected = project(record["camera_matrix"], pupil)
            reprojection = max(abs(projected[0] - reported[0]), abs(projected[1] - reported[1]))
            if reprojection > REPROJECTION_TOLERANCE_PX:
                errors.append(f"{where}: pupil_center_2D_{side} is {reprojection:.3f} px from the projected 3D pupil centre")
            pupil_radius = norm(sub(pupil, centre))
            if pupil_radius < 0.05 * norm(sub(centres["L"], centres["R"])):
                errors.append(f"{where}: the 3D pupil centre of {side} coincides with the eyeball centre")
            side_entry = {"eye_rotation_euler_xyz_degrees": rotation_deg, "gaze_error_to_target_degrees": to_target,
                          "gaze_error_to_pupil_axis_degrees": to_pupil, "pupil_center_world_m": pupil,
                          "pupil_center_2D_metadata_px": reported, "reprojection_error_px": reprojection}
            # Pixels: the dark pupil in the rendered frame, searched for around the eyeball's own projection.
            if rows is not None:
                found = pupil_in_pixels(rows, project(record["camera_matrix"], centre))
                if found is None:
                    errors.append(f"{where}: no pupil found in the pixels of {image.name} for eye {side}")
                else:
                    pixel_error = max(abs(found[0] - reported[0]), abs(found[1] - reported[1]))
                    side_entry["pupil_center_2D_rendered_px"] = found
                    side_entry["rendered_pixel_error_px"] = pixel_error
                    if pixel_error > PIXEL_TOLERANCE_PX:
                        errors.append(f"{where}: pupil_center_2D_{side} is {pixel_error:.2f} px from the pupil in {image.name}")
            entry[side] = side_entry
        # L and R are the subject's own left and right, so the camera sees L on the image-right.
        if record["pupil_center_2D_L"][0] <= record["pupil_center_2D_R"][0]:
            errors.append(f"{where}: pupil L (subject's left) is not right of pupil R in the image")

    sides = [entry[side] for entry in frames_report for side in ("L", "R") if side in entry]
    pixel_errors = [side["rendered_pixel_error_px"] for side in sides if "rendered_pixel_error_px" in side]
    report = {
        "valid": not errors,
        "metadata": metadata_path.name,
        "records": len(records) if isinstance(records, list) else 0,
        "conventions": {"eye_rotation": "world-frame Euler angles, XYZ order (R = Rz Ry Rx), degrees",
                        "pupil_center_2D": "pixels, origin top-left corner, x right, y down",
                        "camera_matrix": "3 x 4 P = K [R | t], world metres to pixels"},
        "tolerances": {"formula": FORMULA_TOLERANCE, "gaze_degrees": GAZE_TOLERANCE_DEGREES,
                       "reprojection_px": REPROJECTION_TOLERANCE_PX, "rendered_pixel_px": PIXEL_TOLERANCE_PX},
        "summary": {
            "max_gaze_error_to_target_degrees": max((side["gaze_error_to_target_degrees"] for side in sides), default=None),
            "max_reprojection_error_px": max((side["reprojection_error_px"] for side in sides), default=None),
            "max_rendered_pixel_error_px": max(pixel_errors, default=None),
            "mean_rendered_pixel_error_px": sum(pixel_errors) / len(pixel_errors) if pixel_errors else None,
            "pupils_located_in_pixels": len(pixel_errors),
            "camera_fixed": bool(usable) and all(record["camera_matrix"] == first_matrix for record in usable),
        },
        "camera": camera_report,
        "frames": frames_report,
        "errors": errors,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    if errors:
        raise MetadataValidationError(errors)
    summary = report["summary"]
    print(f"METADATA_VALIDATION_OK records={report['records']} camera_fixed=true "
          f"max_gaze_error_deg={summary['max_gaze_error_to_target_degrees']:.2e} "
          f"max_reprojection_px={summary['max_reprojection_error_px']:.2e} "
          f"max_rendered_pixel_error_px={summary['max_rendered_pixel_error_px']:.3f}")
    return report


if __name__ == "__main__":
    try:
        validate()
    except MetadataValidationError as error:
        sys.exit(f"METADATA_VALIDATION_FAILED {error}")
