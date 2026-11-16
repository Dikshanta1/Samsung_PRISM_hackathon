"""Validate generated ground truth against the formula, camera, and render pixels."""
from __future__ import annotations

from pathlib import Path
import json
import math
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "metadata.json"
REPORT_PATH = ROOT / "outputs" / "validation_report.json"
PROVENANCE_PATH = ROOT / "metadata" / "official_sequence.json"
REQUIRED = {"frame", "theta", "input", "eye_rotation_L", "eye_rotation_R", "pupil_center_2D_L", "pupil_center_2D_R", "camera_matrix"}


def all_finite(value: object) -> bool:
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(all_finite(item) for item in value)
    if isinstance(value, dict):
        return all(all_finite(item) for item in value.values())
    return True


def png_rows(path: Path) -> list[bytes]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    offset, compressed, header = 8, b"", None
    while offset < len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind, chunk = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + length]
        if kind == b"IHDR": header = chunk
        if kind == b"IDAT": compressed += chunk
        offset += length + 12
    if header is None or struct.unpack(">II", header[:8]) != (1024, 1024) or header[8:13] != bytes((8, 2, 0, 0, 0)):
        raise ValueError(f"Expected 1024x1024 RGB PNG: {path}")
    raw, stride, previous, rows = zlib.decompress(compressed), 1024 * 3, bytes(1024 * 3), []
    for row in range(1024):
        start = row * (stride + 1); filter_type = raw[start]; line = bytearray(raw[start + 1:start + 1 + stride])
        for index in range(stride):
            left = line[index - 3] if index >= 3 else 0
            above = previous[index]
            upper_left = previous[index - 3] if index >= 3 else 0
            if filter_type == 1: line[index] = (line[index] + left) & 255
            elif filter_type == 2: line[index] = (line[index] + above) & 255
            elif filter_type == 3: line[index] = (line[index] + ((left + above) >> 1)) & 255
            elif filter_type == 4:
                estimate = left + above - upper_left; distances = (abs(estimate-left), abs(estimate-above), abs(estimate-upper_left))
                predictor = left if distances[0] <= distances[1] and distances[0] <= distances[2] else above if distances[1] <= distances[2] else upper_left
                line[index] = (line[index] + predictor) & 255
            elif filter_type != 0: raise ValueError(f"Unsupported PNG filter {filter_type}")
        previous = bytes(line); rows.append(previous)
    return rows


def measured_pupil(rows: list[bytes], expected: list[float]) -> list[float]:
    columns, lines = [], []
    u, v = expected
    for row in range(max(0, int(v)-52), min(1024, int(v)+53)):
        line = rows[row]
        for column in range(max(0, int(u)-52), min(1024, int(u)+53)):
            if (column + .5-u)**2 + (row + .5-v)**2 <= 52**2 and max(line[3*column:3*column+3]) < 77:
                columns.append(column); lines.append(row)
    if len(columns) < 100: raise ValueError(f"No pupil found near {expected}")
    return [(min(columns)+max(columns)+1)/2, (min(lines)+max(lines)+1)/2]


def validate(metadata_path: Path = METADATA_PATH) -> dict[str, object]:
    records = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) != 10: raise ValueError("metadata.json must contain exactly ten records")
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))["frames"]
    if len(provenance) != 10: raise ValueError("Sequence provenance must contain exactly ten frames")
    cameras, max_pupil_error = [], 0.0
    for index, record in enumerate(records):
        missing = REQUIRED - record.keys()
        if missing: raise ValueError(f"Frame {index}: missing {sorted(missing)}")
        if record["frame"] != index: raise ValueError(f"Frame numbering error at index {index}")
        theta = 2*math.pi*index/10
        if abs(record["theta"]-theta) > 1e-15: raise ValueError(f"Frame {index}: incorrect theta")
        if abs(record["input"]["h"]-math.sin(theta)) > 1e-15 or abs(record["input"]["v"]-math.cos(theta)) > 1e-15: raise ValueError(f"Frame {index}: incorrect inputs")
        if len(record["eye_rotation_L"]) != 3 or len(record["eye_rotation_R"]) != 3: raise ValueError(f"Frame {index}: invalid rotations")
        if len(record["pupil_center_2D_L"]) != 2 or len(record["pupil_center_2D_R"]) != 2: raise ValueError(f"Frame {index}: invalid pupil coordinates")
        if len(record["camera_matrix"]) != 3 or any(len(row) != 4 for row in record["camera_matrix"]): raise ValueError(f"Frame {index}: invalid camera matrix")
        if not all_finite(record): raise ValueError(f"Frame {index}: contains NaN or infinity")
        measured = provenance[index]
        if measured["frame"] != index or "pupil_center_world_m" not in measured: raise ValueError(f"Frame {index}: missing 3D pupil provenance")
        if not all_finite(measured["pupil_center_world_m"]): raise ValueError(f"Frame {index}: invalid 3D pupil provenance")
        calibration = measured.get("camera_calibration")
        if not calibration or not all_finite(calibration) or calibration.get("projection_matrix_P") != record["camera_matrix"]:
            raise ValueError(f"Frame {index}: invalid calibrated camera provenance")
        image = ROOT / "renders" / f"frame_{record['frame']:02d}.png"
        if not image.is_file(): raise ValueError(f"Frame {index}: missing associated render {image}")
        rows = png_rows(image)
        for side in ("L", "R"):
            predicted = record[f"pupil_center_2D_{side}"]
            observed = measured_pupil(rows, predicted)
            max_pupil_error = max(max_pupil_error, abs(observed[0]-predicted[0]), abs(observed[1]-predicted[1]))
        cameras.append(record["camera_matrix"])
    if any(camera != cameras[0] for camera in cameras[1:]): raise ValueError("Camera matrix changed between frames")
    report = {"valid": True, "records": 10, "formula_verified": True, "camera_fixed": True,
              "max_rendered_pupil_projection_error_px": max_pupil_error, "metadata": str(metadata_path)}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print("METADATA_VALIDATION_OK records=10 formula=true camera_fixed=true " f"max_pupil_error_px={max_pupil_error:.3f}")
    return report


if __name__ == "__main__":
    validate()
