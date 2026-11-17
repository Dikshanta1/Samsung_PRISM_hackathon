# Camera Calibration and Rendering (Stage 3)

All lengths are metres. Every number below is derived by `blender/camera_setup.py` from the camera that is actually in `scene.blend`; `tests/test_camera.py` writes the full-precision values to `metadata/camera_calibration.json`.

## Reference point and distances

The **reference point is the eye midpoint**: the midpoint of the two eyeball rotation centres (the heads of `EyeBone_L` and `EyeBone_R`).

| Quantity | World position (m) | Distance from eye midpoint |
| --- | --- | --- |
| Eye midpoint (reference) | `(0, -0.133, 0.055)` | 0 |
| Fixation target, neutral | `(0, -0.483, 0.055)` | **0.350 m** forward |
| Camera optical centre | `(0, -0.533, 0.055)` | **0.400 m** forward |

"Forward" is the direction the face looks, world `-Y`. The two distances are separate quantities measured from the same point: the 35 cm target belongs to the gaze model (`blender/calibration.py`), the 40 cm camera to this document. The neutral target therefore sits 5 cm in front of the camera, on its optical axis. The target is an empty and never appears in renders.

The 40 cm is measured to the camera's optical centre (the Blender camera object's origin), not to a lens surface. The front of each eyeball is 37 mm nearer the camera than the reference point.

## Fixed camera configuration

| Setting | Value |
| --- | --- |
| Projection | Perspective |
| Focal length | 40 mm |
| Sensor | 36 mm × 24 mm, horizontal fit |
| Lens shift | 0, 0 |
| Field of view | 48.46° horizontal and vertical |
| Clipping | 0.01 m to 10 m |
| Depth of field | Off |
| Resolution | 1024 × 1024 px, 100 %, square pixels |
| Output | 8-bit RGB PNG, no embedded date/time metadata |
| Orientation | Looks along world `+Y` at the eye midpoint, image-up is world `+Z` |

The camera's location, rotation and scale channels are locked, and it has no parent, constraints or animation. `verify_camera()` rejects any scene where the distance, aim, roll, lens, sensor, shift, resolution, pixel aspect, format or locks differ, and names each difference. `render_frame.render_still()` calls it before every render and compares the full camera state before and after.

## Conventions

**Image coordinates** `(u, v)`, in pixels:

- `u` grows to the right, `v` grows downward.
- `(0, 0)` is the top-left corner of the top-left pixel, so the centre of pixel (column, row) is `(column + 0.5, row + 0.5)` and the image centre is `(512, 512)`.
- Blender's `world_to_camera_view` returns normalised `(x, y)` with the origin at the bottom-left; the conversion is `u = x · 1024`, `v = (1 − y) · 1024`.

**Camera coordinates** (computer-vision style): `+X` right, `+Y` down, `+Z` forward along the optical axis. A world point maps as `x_cam = R · x_world + t`, then `[u, v, 1]ᵀ ∼ K · x_cam`. Blender's own camera frame is `+Y` up, `−Z` forward; the two differ by `diag(1, −1, −1)`.

Image-right is world `+X`, which is the subject's left. `Eye_L` is the subject's own left eye, at world `+X`, so it appears on the right of the image; `Eye_R` is at world `−X`, on the left of the image. This follows the Blender / MakeHuman rig convention.

## Calibration

Intrinsic matrix, from `fx = lens · width / sensor_width = 40 · 1024 / 36`:

```text
K = | 1137.7778     0      512 |
    |     0     1137.7778  512 |
    |     0         0        1 |
```

At the eye plane (0.400 m) this is 2844.4 px per metre, or 2.84 px per millimetre.

World-to-camera rotation and translation:

```text
R = | 1  0   0 |        t = | 0     |
    | 0  0  -1 |            | 0.055 |
    | 0  1   0 |            | 0.533 |
```

The camera centre is `C = −Rᵀ t = (0, −0.533, 0.055)`.

Projection matrix `P = K [R | t]`, mapping homogeneous world metres to pixels:

```text
P = | 1137.7778   512        0       272.896 |
    |     0       512   -1137.7778   335.474 |
    |     0         1        0         0.533 |
```

The stored camera rotation is 90° about X held in 32-bit floats, so the JSON file shows entries of about 1.6e-7 where zeros are printed here.

### Known points

Projected with `P` and checked against hand-computed pinhole values (`u = 512 + fx · X / depth`, `v = 512 − fx · Z / depth`):

| World point | u | v | Depth (m) |
| --- | --- | --- | --- |
| Eye midpoint | 512.000 | 512.000 | 0.400 |
| Neutral fixation target | 512.000 | 512.000 | 0.050 |
| `Eye_L` centre | 699.733 | 512.000 | 0.400 |
| `Eye_R` centre | 324.267 | 512.000 | 0.400 |
| 5 cm right of midpoint | 654.222 | 512.000 | 0.400 |
| 5 cm above midpoint | 512.000 | 369.778 | 0.400 |
| 3 cm left, 2 cm below, 10 cm nearer | 398.222 | 587.852 | 0.300 |

### Agreement with Blender

`tests/test_camera.py` compares `P` with two independent Blender projection paths on 500 random points:

| Blender path | Largest difference |
| --- | --- |
| `bpy_extras.object_utils.world_to_camera_view` | 4.4e-4 px |
| `Object.calc_matrix_camera` (Blender's projection matrix) | 2.7e-4 px |

The focal lengths and principal point in `K` are also checked directly against the entries of Blender's projection matrix. To confirm the derivation is general rather than fitted to this camera, the same code is checked on a temporary probe camera with other lenses, sensor fits, lens shifts, poses and non-square resolutions (largest difference 4.3e-4 px); the probe is deleted afterwards.

### 2D pupil centres

`pupil_centres_px()` projects the centre of each pupil's aperture: the mean of the vertices on the open margin of the pupil cap mesh, read from the mesh. In the five test renders the pupil centre measured from the pixels is within 0.7 px of this prediction. 

## Lighting

`blender/lighting_setup.py` defines lighting that does not depend on the eye pose:

| Light | Type | Position (m) | Power | Size |
| --- | --- | --- | --- | --- |
| `KeyLight` | Area, disk | `(-0.32, -0.62, 0.38)` | 5 W | 0.30 m |
| `FillLight` | Area, disk | `(0.34, -0.55, 0.12)` | 2 W | 0.30 m |

Both aim at `(0, -0.10, 0.04)` and are transform-locked. The world is a uniform `(0.025, 0.025, 0.025)` background. Renders use EEVEE with 64 samples and shadows, the Standard view transform, no look, exposure 0 and gamma 1. `verify_lighting()` rejects any deviation, and the full lighting state is compared before and after each render.

## Rendering

```python
from wrapper.renderer import render
path = render("renders/frame.png")      # returns a pathlib.Path
```

or `python3 -m wrapper.renderer renders/frame.png`. To render a chosen pose, use `wrapper.eyes.Eyes` (`docs/WRAPPER_API.md`).

`render(output_path)` starts Blender in background mode on `scene.blend`, renders the eye pose saved there and returns the absolute path of the PNG. It never saves the scene file, so rendering cannot move the camera or change the lighting. It raises `RenderError` with the reason and the tail of Blender's output when:

- the output path does not end in `.png`, or cannot be written;
- the scene file or the Blender executable is missing;
- the camera or lighting is not in the locked configuration (no image is written);
- Blender fails, times out, or produces a file that is not a 1024 × 1024 PNG.

An existing file at the output path is deleted before rendering, so a stale image is never returned.

## Tests

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup scene.blend --python-exit-code 1 --python tests/test_camera.py
```

```bash
python3 tests/test_renderer.py
```

`test_camera.py` checks the configuration, tamper detection, `K`, `R`, `t`, `P`, the known points and the agreement with Blender, then renders `renders/stage3_{centre,left,right,up,down}.png` and verifies for each:

- a valid 8-bit RGB PNG of 1024 × 1024;
- camera state and lighting state identical to the first frame;
- background, forehead, mouth and chin regions pixel-identical to the centre render;
- the pupil, located in the rendered pixels, within 1.5 px of the projected centre.

Measured pupil shifts relative to the centre render, in pixels `(Δu, Δv)`:

| Pose | Input `(h, v)` | `Eye_L` | `Eye_R` |
| --- | --- | --- | --- |
| Left | `(-1, 0)` | `(-15.5, 0.0)` | `(-16.0, 0.0)` |
| Right | `(+1, 0)` | `(+16.0, 0.0)` | `(+15.5, 0.0)` |
| Up | `(0, +1)` | `(0.0, -16.0)` | `(0.0, -16.0)` |
| Down | `(0, -1)` | `(0.0, +16.0)` | `(0.0, +16.0)` |

`test_renderer.py` checks that `render()` returns the path of a 1024 × 1024 PNG, that two renders of the same pose are byte-identical, that `scene.blend` is unchanged, and that each failure above is reported.
