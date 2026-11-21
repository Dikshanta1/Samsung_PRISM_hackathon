"""Ordinary-Python acceptance test for the public :class:`wrapper.eyes.Eyes`.

    python3 tests/test_wrapper.py

Runs under system Python (no ``bpy``) against the real ``scene.blend``;
nothing is mocked. It checks that Blender launches and loads that scene, that
inputs are validated, that movement and reset are real and do not accumulate,
that renders are valid PNGs in which the pupils actually move, that output
directories are configurable, that failures are reported, and that the scene
file (and so the camera calibration) is never modified.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wrapper.blender_runner import blender_executable
from wrapper.eyes import DEFAULT_SCENE, BlenderWorkerError, Eyes
from wrapper.renderer import png_size, render as render_saved_scene
from metadata.pupil_pixels import MASK_BAND_ROWS, mask_centroids, pupil_contrast_problem

MIN_SHIFT_PX = 10.0  # a full-range move shifts each pupil by about 12 px
CROSS_AXIS_PX = 1.0
PIXEL_TOLERANCE_PX = 0.25  # pupil drawn in the mask render versus the centre Blender reports
EYE_ROWS_LAST = 640  # decoding rows 0..640 covers both eyes at every allowed gaze
FOREHEAD = ((130, 250), (440, 580))  # rows, columns: no eye pixels, so it must never change
DIRECTIONS = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "up": (0.0, 1.0), "down": (0.0, -1.0)}
EXPECTED_SIGN = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}  # (du, dv); v grows downward


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_png_rows(path: Path, last_row: int) -> list[bytes]:
    """Decode rows 0..last_row of an 8-bit RGB, non-interlaced PNG (standard library only)."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    position, compressed, header = 8, b"", None
    while position < len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        assert zlib.crc32(kind + body) == int.from_bytes(data[position + 8 + length:position + 12 + length], "big"), "PNG chunk CRC mismatch"
        if kind == b"IHDR":
            header = body
        elif kind == b"IDAT":
            compressed += body
        position += 12 + length
    assert header is not None and kind == b"IEND", f"{path} is truncated"
    width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
    assert (width, height) == (1024, 1024), f"{path} is {width} x {height}"
    assert header[8:13] == bytes((8, 2, 0, 0, 0)), f"{path} is not 8-bit RGB, non-interlaced"
    raw = zlib.decompress(compressed)
    stride = width * 3
    assert len(raw) == height * (stride + 1), f"{path} holds the wrong amount of pixel data"
    rows, previous = [], bytes(stride)
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
        else:
            assert filter_type == 0, f"Unknown PNG filter {filter_type}"
        previous = bytes(line)
        rows.append(previous)
    return rows


# EEVEE on the GPU reproduces a frame to within one 8-bit level in a handful of pixels
# (dithered transparency of hair and lashes); "the same image" means within this.
SAME_IMAGE_MAX_LEVELS = 2
SAME_IMAGE_MAX_PIXELS = 64  # of 1,048,576


def image_difference(a: Path, b: Path) -> tuple[int, int]:
    """(pixels that differ, largest difference in 8-bit levels) between two renders."""
    rows_a, rows_b = read_png_rows(a, 1023), read_png_rows(b, 1023)
    count = largest = 0
    for line_a, line_b in zip(rows_a, rows_b):
        if line_a == line_b:
            continue
        for column in range(0, len(line_a), 3):
            delta = max(abs(line_a[column + i] - line_b[column + i]) for i in range(3))
            if delta:
                count += 1
                largest = max(largest, delta)
    return count, largest


def assert_same_image(a: Path, b: Path, message: str) -> None:
    count, largest = image_difference(a, b)
    assert count <= SAME_IMAGE_MAX_PIXELS and largest <= SAME_IMAGE_MAX_LEVELS, \
        f"{message} ({count} pixels differ, by up to {largest} levels)"


def assert_same_region(a: bytes, b: bytes, message: str) -> None:
    largest = max((abs(x - y) for x, y in zip(a, b)), default=0)
    assert len(a) == len(b) and largest <= SAME_IMAGE_MAX_LEVELS, f"{message} (by up to {largest} levels)"


def region(rows: list[bytes], area: tuple[tuple[int, int], tuple[int, int]]) -> bytes:
    (r0, r1), (c0, c1) = area
    return b"".join(rows[row][3 * c0:3 * c1] for row in range(r0, r1))


def expect(label: str, exception: type[Exception], fragment: str, call) -> None:
    try:
        call()
    except exception as error:
        assert fragment.lower() in str(error).lower(), f"{label}: error does not explain the failure: {error}"
        print(f"REPORTED {label}: {type(error).__name__}: {str(error).splitlines()[0]}")
    else:
        raise AssertionError(f"{label}: no {exception.__name__} was raised")


def comparable(state: dict) -> dict:
    return {key: value for key, value in state.items() if key != "action"}


def check_direction(name: str, state: dict, centre: dict) -> None:
    sign_u, sign_v = EXPECTED_SIGN[name]
    for side in ("L", "R"):
        du = state["pupil_center_2D"][side][0] - centre["pupil_center_2D"][side][0]
        dv = state["pupil_center_2D"][side][1] - centre["pupil_center_2D"][side][1]
        along, across = (du * sign_u, dv) if sign_u else (dv * sign_v, du)
        assert along >= MIN_SHIFT_PX, f"{name}: pupil {side} moved {along:.2f} px in the commanded direction"
        assert abs(across) < CROSS_AXIS_PX, f"{name}: pupil {side} drifted {across:.2f} px across the commanded axis"
    assert max(state["angular_error_degrees"].values()) < 0.001, f"{name}: eyes are not on the target"
    alignment = state["binocular_alignment"]
    assert alignment["gaze_angle_between_eyes_degrees"] < 1e-3 and alignment["rotation_difference_degrees"] < 1e-3, \
        f"{name}: the eyes do not move together ({alignment})"
    rotations = state["eye_rotation_euler_xyz_degrees"]
    assert max(abs(a - b) for a, b in zip(rotations["L"], rotations["R"])) < 1e-3, f"{name}: left and right rotations differ"


def main() -> None:
    assert "bpy" not in sys.modules, "The wrapper imported bpy into system Python"
    scene_before = digest(DEFAULT_SCENE)
    backup = DEFAULT_SCENE.with_suffix(".blend1")
    backup_before = backup.stat().st_mtime_ns if backup.exists() else None

    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary).resolve()
        eyes = Eyes(base / "run_a")

        # Blender really launches and loads the real scene.
        centre = eyes.reset()
        assert Path(centre["scene"]).resolve() == DEFAULT_SCENE.resolve(), f"Wrong scene loaded: {centre['scene']}"
        assert centre["blender_version"], "Blender did not report its version"
        assert centre["inputs"] == {"h": 0.0, "v": 0.0} and eyes.position == (0.0, 0.0)
        assert max(centre["angular_error_degrees"].values()) < 0.001
        print(f"BLENDER_LAUNCH_OK version={centre['blender_version']} scene={centre['scene']}")

        # Inputs outside [-1, +1] and non-numbers are rejected before Blender is started.
        eyes.move(0.25, -0.5)
        for h, v in ((1.01, 0.0), (-1.01, 0.0), (0.0, 1.0001), (0.0, -2.0), (float("nan"), 0.0),
                     (0.0, float("inf")), ("1", 0.0), (0.0, None), (True, 0.0)):
            expect(f"move({h!r}, {v!r})", ValueError, "[-1, +1]", lambda h=h, v=v: eyes.move(h, v))
        assert eyes.position == (0.25, -0.5), "A rejected input changed the current pose"
        for h, v in ((1, 0), (-1.0, -1.0), (1.0, 1.0), (0, 0)):  # the bounds themselves and ints are valid
            assert eyes.move(h, v)["inputs"] == {"h": float(h), "v": float(v)}
        print("INPUT_VALIDATION_OK")

        # Movement is real, in the commanded direction, for both eyes.
        states = {name: eyes.move(*pose) for name, pose in DIRECTIONS.items()}
        for name, state in states.items():
            check_direction(name, state, centre)
            assert state["camera_fixed"] and state["lighting_constant"]
            assert state["camera_matrix"] == centre["camera_matrix"], f"{name}: camera matrix changed"
        print("MOVEMENT_OK " + " ".join(
            f"{name}=({states[name]['pupil_center_2D']['L'][0] - centre['pupil_center_2D']['L'][0]:+.1f},"
            f"{states[name]['pupil_center_2D']['L'][1] - centre['pupil_center_2D']['L'][1]:+.1f})px" for name in DIRECTIONS))

        # Repeated movements do not accumulate: the pose depends only on the last input.
        for _ in range(3):
            repeated = eyes.move(1.0, 0.0)
            assert comparable(repeated) == comparable(states["right"]), "Repeating move(1, 0) changed the pose"
        for pose in ((-1.0, 1.0), (0.3, -0.7), (1.0, 1.0), (-0.4, 0.2)):
            eyes.move(*pose)
        assert comparable(eyes.move(1.0, 0.0)) == comparable(states["right"]), "The pose depends on earlier movements"
        assert comparable(eyes.reset()) == comparable(centre), "reset() after movement is not the neutral pose"
        assert eyes.position == (0.0, 0.0)
        print("REPEATED_MOVEMENT_OK accumulated_rotation=none reset_exact=true")

        # Rendering: real PNGs, default names in the configured directory.
        neutral_png = eyes.render(pupil_mask=True)
        assert neutral_png == base / "run_a" / "eye_render_0001.png" and neutral_png.is_file()
        neutral_report = eyes.last_render
        neutral_mask = base / "run_a" / "eye_render_0001_pupil_mask.png"
        assert neutral_report["pupil_mask"]["output"] == str(neutral_mask) and neutral_mask.is_file()
        eyes.move(-1.0, 0.0)
        left_png = eyes.render("left.png", pupil_mask="left_mask.png")
        assert left_png == base / "run_a" / "left.png"
        left_report = eyes.last_render
        eyes.move(1.0, 0.0)
        right_png = eyes.render(base / "elsewhere" / "nested" / "right.png", pupil_mask=True)  # absolute path, new folders
        assert right_png == base / "elsewhere" / "nested" / "right.png"
        right_report = eyes.last_render
        eyes.reset()
        reset_png = eyes.render()
        assert reset_png == base / "run_a" / "eye_render_0002.png" and "pupil_mask" not in eyes.last_render
        for path in (neutral_png, left_png, right_png, reset_png):
            assert png_size(path) == (1024, 1024) and path.stat().st_size > 10_000, f"{path} is not a real render"
        assert len({digest(neutral_png), digest(left_png), digest(right_png)}) == 3, "Different poses rendered identically"
        assert_same_image(reset_png, neutral_png, "The render after reset() differs from the neutral render")
        saved_png = render_saved_scene(base / "saved_scene.png")
        assert_same_image(saved_png, neutral_png, "reset() does not match the neutral pose saved in the scene")
        assert not (base / "run_a" / "eye_render_0002_pupil_mask.png").exists(), "A pupil mask was written without being asked for"

        # The pupils move in the rendered pixels, and nothing else does. The pupil-mask
        # render shows where the renderer drew each pupil; the photoreal frame must be dark there.
        reports = {"centre": neutral_report, "left": left_report, "right": right_report}
        pixels = {name: read_png_rows(path, EYE_ROWS_LAST) for name, path in
                  (("centre", neutral_png), ("left", left_png), ("right", right_png))}
        measured = {}
        for name, rows in pixels.items():
            assert_same_region(region(rows, FOREHEAD), region(pixels["centre"], FOREHEAD), f"{name}: the forehead changed")
            mask = Path(reports[name]["pupil_mask"]["output"])
            found = mask_centroids(read_png_rows(mask, MASK_BAND_ROWS[1]))
            for side in ("L", "R"):
                predicted = reports[name]["pupil_center_2D"][side]
                error = max(abs(found[side][0] - predicted[0]), abs(found[side][1] - predicted[1]))
                assert error <= PIXEL_TOLERANCE_PX, f"{name} {side}: rendered pupil is {error:.3f} px from the reported centre"
                problem = pupil_contrast_problem(rows, predicted)
                assert problem is None, f"{name} {side}: the reported pupil centre {problem}"
                measured[name, side] = found[side]
        for side in ("L", "R"):
            assert measured["left", side][0] - measured["centre", side][0] <= -MIN_SHIFT_PX, f"left: rendered pupil {side} did not move left"
            assert measured["right", side][0] - measured["centre", side][0] >= MIN_SHIFT_PX, f"right: rendered pupil {side} did not move right"
        print("RENDER_OK size=1024x1024 rendered_shift_L="
              f"{measured['left', 'L'][0] - measured['centre', 'L'][0]:+.1f}/{measured['right', 'L'][0] - measured['centre', 'L'][0]:+.1f}px "
              "pupil_masks=true reset_render_identical=true")

        # A second object with another output directory is independent of the first.
        other = Eyes(output_dir=base / "run_b")
        assert other.position == (0.0, 0.0)
        other_png = other.render()
        assert other_png == base / "run_b" / "eye_render_0001.png"
        assert_same_image(other_png, neutral_png, "A new Eyes object does not start in the neutral pose")
        print(f"OUTPUT_DIRECTORIES_OK {neutral_png.parent.name} {other_png.parent.name} {right_png.parent}")

        # The dataset script uses the same public API.
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_dataset.py"), "--output-dir",
                                    str(base / "dataset"), "--pose=-1,0", "--pose=0,1"], text=True, capture_output=True)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        manifest = json.loads((base / "dataset" / "dataset.json").read_text(encoding="utf-8"))
        assert [frame["input"] for frame in manifest["frames"]] == [{"h": -1.0, "v": 0.0}, {"h": 0.0, "v": 1.0}]
        for frame in manifest["frames"]:
            assert png_size(base / "dataset" / frame["image"]) == (1024, 1024)
            assert frame["camera_matrix"] == centre["camera_matrix"]
        assert_same_image(base / "dataset" / "frame_0000.png", left_png, "The dataset script rendered a different left gaze")
        print("DATASET_SCRIPT_OK frames=2")

        # Failures are reported, not swallowed.
        expect("missing scene", FileNotFoundError, "not found", lambda: Eyes(scene=base / "missing.blend"))
        expect("non-PNG output", BlenderWorkerError, ".png", lambda: eyes.render("frame.jpg"))
        expect("non-PNG pupil mask", BlenderWorkerError, ".png", lambda: eyes.render("frame.png", pupil_mask="mask.jpg"))
        expect("timeout", BlenderWorkerError, "did not finish", lambda: Eyes(base, timeout=0.001).move(0.0, 0.0))
        empty = base / "empty.blend"
        subprocess.run([str(blender_executable()), "--background", "--factory-startup", "--python-expr",
                        f"import bpy; bpy.ops.wm.save_as_mainfile(filepath={str(empty)!r})"],
                       check=True, capture_output=True, text=True)
        expect("wrong scene (move)", BlenderWorkerError, "not the eye scene", lambda: Eyes(base, scene=empty).move(1.0, 0.0))
        expect("wrong scene (render)", BlenderWorkerError, "not the eye scene", lambda: Eyes(base, scene=empty).render("x.png"))
        assert not (base / "x.png").exists(), "An image was written for the wrong scene"

    # The scene file, and with it the camera calibration and lighting, was never written.
    assert digest(DEFAULT_SCENE) == scene_before, "The wrapper modified scene.blend"
    assert (backup.stat().st_mtime_ns if backup.exists() else None) == backup_before, "The wrapper saved the scene"
    assert "bpy" not in sys.modules
    print("WRAPPER_TEST_OK blender=true scene=real movement=true reset=true render=true scene_untouched=true")


if __name__ == "__main__":
    main()
