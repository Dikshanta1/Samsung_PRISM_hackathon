# Synthetic Eye Movement & Virtual Camera Rendering

Samsung PRISM Hackathon 2026, Track 1.

## 1. Project overview

A Blender scene with a textured, photoreal human head (a Character Creator 3 character) and two independently rigged eyeballs, driven from ordinary Python:

```python
from wrapper.eyes import Eyes

eyes = Eyes()
eyes.move(1, 0)      # both eyes fixate a target to the image-right
eyes.render()        # 1024 x 1024 PNG through a locked, calibrated camera
eyes.reset()
```

The bundle contains the scene (`scene.blend`), the wrapper (`wrapper/eyes.py`), the ten official clockwise renders (`renders/`), their ground-truth metadata (`metadata.json`), a pupil-mask render per frame (`outputs/pupil_masks/`), and the sources and tests that regenerate and verify all of it.

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
scripts/package_submission.py                   blender/pupil_mask.py       pupil-only render for verification
metadata/pupil_pixels.py  pixel checks           blender/eyelids.py          lids follow the gaze
                                                blender/character_asset.py  import + fix the CC3 head
                                                blender/eye_rig.py, build_scene.py   build scene.blend
```

- `bpy` only runs inside Blender, so every wrapper call starts Blender in background mode on `scene.blend`, runs `scripts/blender_worker.py`, and reads back one JSON line.
- The current `(h, v)` lives in the `Eyes` object and is sent as an absolute pose each time. Movements cannot accumulate, and **`scene.blend` is never saved**, so the neutral pose, camera and lighting in it cannot be altered by use.
- `move(h, v)` places the fixation target at eye midpoint + 0.35 m forward + 0.05 m × `(h, v)`. Both eyes turn **together, by the same rotation**, so their optical axes are parallel to the line from the eye midpoint to the target. At `(0, 0)` both look straight ahead; at `(1, 0)` both turn 8.13° right. The eyes never cross or move independently (see `docs/EYE_MOVEMENT.md`).
- Before and after every command the worker verifies the camera and lighting against the locked configuration and refuses to continue if anything differs.
- **The head** is the Character Creator rig `FaceRig` (skin, lashes, brows, hair, beard, teeth). Its two eyeballs are baked out of the CC3 eye mesh into rigid objects `Eye_L` / `Eye_R`. Each pivots on the centre of a sphere fitted to its sclera, and its optical axis points at the pupil painted in the iris texture. The eyeballs are children of `EyeBone_L` / `EyeBone_R` in `EyeRig`, which rides on the head bone. Rotating a bone can only turn its eye about its centre.
- **Pupil ground truth.** The pupil is painted in the texture, so the build maps the texture's pupil margin through the mesh UVs onto the eyeball as an invisible landmark (`Pupil_L` / `Pupil_R`, never rendered). Its centre is projected through the camera for `pupil_center_2D`. To check this against the renderer, each official frame also has a *pupil-mask render*: the same pose and camera with only the textured pupils, white on black. The mask centroids agree with the metadata to within 0.03 px.
- **Lid follow.** The upper and lower lids track vertical and horizontal gaze through Character Creator's eye-look shape keys (`blender/eyelids.py`). Only lids move; eyeball rotations and pupil positions are unaffected.

Coordinates: metres; world `+X` is image-right, `+Z` is up, the face looks along `−Y`; the character stands on the ground plane, so the eye midpoint is at (0, −0.0265, 1.7216). `Eye_L` is the subject's own left eye (world `+X`, right side of the image).

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

Contents: `FaceRig` (the Character Creator skeleton) with the textured body, hair, brows, beard, lashes, teeth and eye-occlusion meshes; `EyeRig` (armature with `EyeBone_L`, `EyeBone_R`, parented to the head bone); `Eye_L` / `Eye_R` (eyeball and cornea) with the hidden landmark `Pupil_*`; `Camera` (locked); `KeyLight`, `FillLight`; and the `FixationTarget` empty. Every texture is packed, so the file is self-contained (about 38 MB). It is saved in the neutral pose. Press Numpad 0 for the camera view; rotate a bone in Pose Mode to move an eye by hand.

To rebuild it from code you need the character source `Hassan+V1.blend`, which is not in the bundle (see §15). Put it at `assets/source/Hassan+V1.blend`, or point `TRACK1_CHARACTER_BLEND` at it, then:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python blender/build_scene.py -- renders
```

The build appends only the metre-scale character and replaces the materials whose maps were missing from the source with clean PBR node trees. It bakes and fits the eyeballs, keeps only the eye-related shape keys, packs the textures and saves `scene.blend`. It takes about 10 seconds.

## 8. How to use eyes.move()

```python
from wrapper.eyes import Eyes
eyes = Eyes()                 # optional: Eyes(output_dir="my_folder")
state = eyes.move(-1, 0.5)    # h, v in [-1, +1]
```

- `h = +1` looks image-right, `h = −1` image-left, `v = +1` up, `v = −1` down. Full range is ±5 cm at the 35 cm target plane, which turns each eye by about 8° and moves each pupil by about 12 px in the image.
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

Renders the current pose to a 1024 × 1024 8-bit RGB PNG and returns its absolute `pathlib.Path`. Missing folders are created. `eyes.render(pupil_mask=True)` also writes `<name>_pupil_mask.png`, the same view with only the pupils, white on black; you can also pass a path. Blender's measurements for that frame are in `eyes.last_render`. Any failure (Blender missing, wrong scene, changed camera or lighting, timeout, invalid output) raises `BlenderWorkerError` with the reason.

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

- **Third-party character.** The head comes from a Character Creator 3 export (`Hassan+V1.blend`), not from one of the open assets the brief lists (MakeHuman / MPFB, GNM, FLAME). See §15 before redistributing.
- **Reconstructed materials.** The source file referenced about a hundred auxiliary maps (AO, SSS, micro-normal, sclera) that are not in it. Those materials were rebuilt from the maps that are embedded (diffuse, normal, opacity). The iris brightness and white sclera that the original Character Creator eye shader provides are recreated with UV masks.
- **Physically sized eye movement.** The head is life-size (66.8 mm between eye centres), so the full ±5 cm range turns each eye by about 8° and moves each pupil by about 12 px. That is visible, but small at contact-sheet scale. The 70 mm lens frames the face from hairline to chin to make it as large as the 40 cm camera allows.
- **No corneal refraction.** The cornea is a clear, reflective shell; it does not bend light, so the visible pupil is exactly the geometric one the metadata reports.
- **Hair cards cast no shadows.** Their dithered-alpha shadows were not reproducible on the GPU. Renders are reproducible to within 2 levels on at most 64 pixels, and identical in nearly all runs. Tests compare images within that bound.
- **Tested only with Blender 5.3.0 on macOS (Apple Silicon).** Other versions or GPUs may differ slightly.
- **Speed.** Each wrapper call starts a new Blender process: about 2 s per move and 3 s per render (plus about 1 s for a pupil mask).
- **Square input range.** `h` and `v` are limited separately, so a corner such as `(1, 1)` puts the target 7.07 cm from centre. The official circle stays within 5 cm.

## 15. Asset attribution and licences

- **Character: "Hassan V1"**, a Character Creator 3 (Reallusion) character exported to Blender. The mesh, rig, shape keys and textures in `scene.blend` come from it. **Its licence has not been verified.** Character Creator content is normally covered by Reallusion's EULA, which can restrict redistributing editable meshes and textures. Confirm that the character may be redistributed in a hackathon submission before publishing `scene.blend`. If it may not, rebuild with an open head (MakeHuman / MPFB is CC0); the build only needs a CC3-style eye mesh and eye-look shape keys.
- The source `.blend` (347 MB) is not part of the bundle or the git repository (`assets/source/` is git-ignored).
- **Blender** (GPL-2.0-or-later, <https://www.blender.org>) is required to run the project but is not redistributed. The contact-sheet labels use Blender's built-in font at render time.
- **Python standard library** only; no other dependencies.
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
| `outputs/` | `contact_sheet.png`, `pupil_masks/frame_00..09.png`, `validation_report.json`, `final_validation_report.json` |
| `docs/` | Calibration, wrapper API, sequence, metadata, demo script |
