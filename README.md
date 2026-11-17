# Synthetic Eye Movement & Virtual Camera Rendering

Samsung PRISM Hackathon 2026, Track 1.

## 1. Project overview

A Blender scene with a face and two independently rigged eyeballs, driven from ordinary Python:

```python
from wrapper.eyes import Eyes

eyes = Eyes()
eyes.move(1, 0)      # both eyes fixate a target to the image-right
eyes.render()        # 1024 x 1024 PNG through a locked, calibrated camera
eyes.reset()
```

The bundle contains the scene (`scene.blend`), the wrapper (`wrapper/eyes.py`), the ten official clockwise renders (`renders/`), their ground-truth metadata (`metadata.json`), and the sources and tests that regenerate and verify all of it.

## 2. Problem statement

Track 1 asks for synthetic eye-movement data with exact ground truth:

- a face with left and right eye bones;
- both eyes fixating a target 35 cm in front of the eye midpoint, moved within ±5 cm by normalised inputs `h, v` in `[-1, +1]`;
- a camera locked 40 cm in front of the face, 1024 × 1024 PNG output, constant lighting;
- a deterministic Python interface `eyes.move(h, v)`, `eyes.reset()`, `eyes.render()`;
- ten clockwise renders at `θk = 2πk/10`, `h = sin θk`, `v = cos θk`, starting at the top;
- per-frame metadata: inputs, world-frame eye rotations, 2D pupil centres and the camera matrix.

## 3. Architecture

```text
ordinary Python (no bpy)                      Blender's Python (bpy)
------------------------                      ----------------------
wrapper/eyes.py        Eyes.move/reset/render
wrapper/renderer.py    PNG render + checks      scripts/blender_worker.py   one command per process
wrapper/blender_runner.py  finds Blender   -->  blender/calibration.py      h, v -> target -> eye rotations
scripts/generate_official_sequence.py           blender/camera_setup.py     locked camera, K, R, t, P
metadata/metadata_generator.py                  blender/lighting_setup.py   constant lighting
metadata/validator.py                           blender/render_frame.py     guarded still render
scripts/package_submission.py                   blender/eye_rig.py, build_scene.py   build scene.blend
```

- `bpy` only runs inside Blender, so every wrapper call starts Blender in background mode on `scene.blend`, runs `scripts/blender_worker.py`, and reads back one JSON line.
- The current `(h, v)` lives in the `Eyes` object and is sent as an absolute pose each time. Movements cannot accumulate, and **`scene.blend` is never saved**, so the neutral pose, camera and lighting in it cannot be altered by use.
- `move(h, v)` places the fixation target at eye midpoint + 0.35 m forward + 0.05 m × `(h, v)` and turns each eye about its own centre to look at it, so the eyes converge.
- Before and after every command the worker verifies the camera and lighting against the locked configuration and refuses to continue if anything differs.

Coordinates: metres; world `+X` is image-right, `+Z` is up, the face looks along `−Y`. `Eye_L` is the subject's own left eye (world `+X`, right side of the image).

## 4. Technology stack

- Blender 5.3.0 (EEVEE renderer), driven in background mode.
- Python 3.10 or newer for the wrapper and tests, standard library only. No `pip` packages are needed.
- Blender's bundled Python (`bpy`, `mathutils`, `bmesh`) for scene code.

## 5. Installation

1. Install Blender 5.3 from <https://www.blender.org/download/>.
2. Install Python 3.10+ (any standard CPython).
3. Unzip the bundle and open a terminal in its top folder. There is nothing else to install.

## 6. Blender setup

The wrapper finds Blender in this order:

1. the `BLENDER_BIN` environment variable;
2. a `blender` command on `PATH`;
3. `/Applications/Blender.app/Contents/MacOS/Blender` (macOS default).

On Windows or Linux, or with Blender installed elsewhere, set the variable once:

```bash
export BLENDER_BIN=/path/to/blender
```

No add-ons, preferences or online access are required. Blender is always started with `--factory-startup`.

## 7. How to open scene.blend

Double-click `scene.blend`, or use File > Open in Blender, or:

```bash
/Applications/Blender.app/Contents/MacOS/Blender scene.blend
```

Contents: `EyeRig` (armature with `EyeBone_L`, `EyeBone_R`), `Eye_L` / `Eye_R` with child `Iris_*` and `Pupil_*`, `HumanHead` and facial features, `Camera` (locked), `KeyLight`, `FillLight`, and the `FixationTarget` empty. It is saved in the neutral pose. Press Numpad 0 for the camera view; rotate a bone in Pose Mode to move an eye by hand.

To rebuild it from code:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python blender/build_scene.py -- renders
```

## 8. How to use eyes.move()

```python
from wrapper.eyes import Eyes
eyes = Eyes()                 # optional: Eyes(output_dir="my_folder")
state = eyes.move(-1, 0.5)    # h, v in [-1, +1]
```

- `h = +1` looks image-right, `h = −1` image-left, `v = +1` up, `v = −1` down. Full range is ±5 cm at the 35 cm target plane.
- Each call sets the pose outright; it does not add to the previous one.
- Values outside `[-1, +1]`, NaN, infinities and non-numbers raise `ValueError` before Blender starts.
- Returns what Blender measured: `inputs`, `fixation_target_world_m`, `angular_error_degrees`, `eye_rotation_euler_xyz_degrees`, `pupil_center_2D`, `camera_matrix` and more.

Run from the bundle's top folder (or put it on `PYTHONPATH`).

## 9. How to use eyes.reset()

```python
state = eyes.reset()
```

Returns both eyes to the calibrated neutral pose `(0, 0)`, fixating the point 35 cm straight ahead. It sets the pose directly; it does not undo earlier moves. A new `Eyes()` also starts at neutral.

## 10. How to use eyes.render()

```python
path = eyes.render()                      # outputs/eye_render_0001.png, then 0002, ...
path = eyes.render("left.png")            # <output_dir>/left.png
path = eyes.render("/tmp/run/left.png")   # exactly this path
```

Renders the current pose to a 1024 × 1024 8-bit RGB PNG and returns its absolute `pathlib.Path`. Missing folders are created. Blender's measurements for that frame are in `eyes.last_render`. Any failure (Blender missing, wrong scene, changed camera or lighting, timeout, invalid output) raises `BlenderWorkerError` with the reason.

Full reference: `docs/WRAPPER_API.md`.

## 11. How to generate the ten images

```bash
python3 scripts/generate_official_sequence.py
```

Deletes earlier frames, then for `k = 0..9` moves the eyes to `h = sin(2πk/10)`, `v = cos(2πk/10)` and renders `renders/frame_00.png` to `renders/frame_09.png`: top, upper-right, right-upper, right-lower, lower-right, bottom, lower-left, left-lower, left-upper, upper-left. It also writes `outputs/contact_sheet.png` and checks its own output. About 35 seconds. Details: `docs/OFFICIAL_SEQUENCE.md`.

## 12. How to generate metadata

The same command writes `metadata.json` (it is produced from the Blender process that renders each frame). To run only that part by name:

```bash
python3 metadata/metadata_generator.py
```

`metadata.json` is an array of ten records:

| Field | Meaning |
| --- | --- |
| `frame` | 0 to 9; record `k` describes `renders/frame_0k.png` |
| `theta` | `2πk/10`, radians |
| `input` | `{"h": sin θ, "v": cos θ}` |
| `eye_rotation_L`, `eye_rotation_R` | `[rx, ry, rz]`: world-frame Euler angles, XYZ order (`R = Rz·Ry·Rx`), **degrees**. `rz > 0` is image-right, `rx < 0` is up, `ry` is 0 |
| `pupil_center_2D_L`, `pupil_center_2D_R` | `[x, y]` pixels, origin top-left, `x` right, `y` down |
| `camera_matrix` | 3 × 4 `P = K [R | t]`, world metres to pixels |

`L` is the subject's own left eye, which appears on the right of the image. Details: `docs/METADATA.md`, `docs/CAMERA_CALIBRATION.md`.

## 13. How to validate the project

Everything, including a fresh ZIP and a test of that ZIP in an empty folder (about 7 minutes):

```bash
python3 scripts/package_submission.py --team-name team_name
```

This writes `outputs/final_validation_report.json`. Individual checks:

```bash
B=/Applications/Blender.app/Contents/MacOS/Blender
$B --background --factory-startup scene.blend --python-exit-code 1 --python tests/test_eye_rig.py     # scene loads, rig is correct
$B --background --factory-startup scene.blend --python-exit-code 1 --python tests/test_directions.py  # left, right, up, down, reset
$B --background --factory-startup scene.blend --python-exit-code 1 --python tests/test_camera.py      # calibration and renders
python3 tests/test_wrapper.py       # Eyes API from system Python
python3 tests/test_renderer.py      # render() and failure reporting
python3 tests/test_metadata.py      # regenerate ten frames + metadata, validate against pixels
python3 metadata/validator.py       # validate the existing metadata.json only
```

Each prints a line ending in `_OK` on success and exits non-zero on failure.

## 14. Known limitations

- **The face is a procedural stand-in.** It is built from primitives with plain materials, not a textured MakeHuman / GNM / FLAME head. MPFB could not be installed because Blender's online access was disabled on the build machine.
- **The head is about twice human size** (132 mm between eye centres, 37 mm eyeball radius). Neutral vergence is therefore 10.68° per eye, and a full-range move shifts each pupil by about 16 px.
- **No eyelids, lashes or tear film.**
- **Tested only with Blender 5.3.0 on macOS (Apple Silicon).** Renders are byte-identical between runs there; other versions or GPUs may differ slightly.
- **Speed.** Each wrapper call starts a new Blender process: about 1.5 s per move and 2 s per render.
- **Square input range.** `h` and `v` are limited separately, so a corner such as `(1, 1)` puts the target 7.07 cm from centre. The official circle stays within 5 cm.

## 15. Asset attribution and licences

- **No third-party assets are included.** All geometry, materials and lighting are generated by `blender/build_scene.py`; there are no image textures, downloaded meshes or fonts. `assets/` is empty.
- **Blender** (GPL-2.0-or-later, <https://www.blender.org>) is required to run the project but is not redistributed. The contact-sheet labels use Blender's built-in font at render time.
- **Python standard library** only; no other dependencies.
- MakeHuman / MPFB was evaluated (`docs/ENVIRONMENT_REPORT.md`, `docs/STAGE1_ASSET_AND_RIG_REPORT.md`) but nothing from it is used.
- No licence has been chosen for this project's own code yet.

## Folder guide

| Path | Contents |
| --- | --- |
| `scene.blend` | The scene, saved in the neutral pose |
| `wrapper/` | `eyes.py` (public API), `renderer.py`, `blender_runner.py` |
| `blender/` | Scene code that runs inside Blender |
| `scripts/` | Blender worker, sequence generator, contact sheet, packaging |
| `metadata/` | `metadata_generator.py`, `validator.py` |
| `tests/` | Acceptance tests |
| `renders/` | `frame_00.png` to `frame_09.png` |
| `metadata.json` | Ground truth for the ten frames |
| `outputs/` | `contact_sheet.png`, `validation_report.json`, `final_validation_report.json` |
| `docs/` | Calibration, wrapper API, sequence, metadata, demo script |
