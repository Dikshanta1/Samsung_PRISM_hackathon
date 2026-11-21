# Ground-Truth Metadata (Stage 5B)

```bash
python3 tests/test_metadata.py        # render, generate, validate, and test the validator (about 90 s)
python3 metadata/metadata_generator.py  # render and generate only
python3 metadata/validator.py           # validate the existing files only
```

Outputs: `metadata.json` (project root) and `outputs/validation_report.json`. Both are generated and ignored by git.

## `metadata.json`

A JSON array of ten records, one per render, in frame order. Record `k` describes `renders/frame_0k.png`.

```json
{
  "frame": 3,
  "theta": 1.8849555921538759,
  "input": { "h": 0.9510565162951536, "v": -0.30901699437494734 },
  "eye_rotation_L": [2.5047, 0.0, 7.7371],
  "eye_rotation_R": [2.5047, 0.0, 7.7371],
  "pupil_center_2D_L": [696.730, 515.697],
  "pupil_center_2D_R": [350.023, 515.697],
  "camera_matrix": [[1991.111, 512.0, 0.0, 218.368], [0.0, 512.0, -1991.111, 3646.265], [0.0, 1.0, 0.0, 0.4265]]
}
```

(Values shortened here; the file holds full precision.)

| Field | Meaning | Source |
| --- | --- | --- |
| `frame` | `k`, 0 to 9 | sequence index |
| `theta` | `2πk/10`, radians | formula |
| `input` | `h = sin θ`, `v = cos θ` | formula; the values sent to `Eyes.move` |
| `eye_rotation_L/R` | `[rx, ry, rz]`, degrees | `Eye_L` / `Eye_R` `matrix_world.to_euler("XYZ")` of the posed eyeballs |
| `pupil_center_2D_L/R` | `[x, y]`, pixels | 3D pupil centre projected through the scene camera |
| `camera_matrix` | 3 × 4 `P = K [R | t]` | derived from the scene camera (`blender/camera_setup.py`) |

All of these are read in the Blender process that renders the frame (`scripts/blender_worker.py`); none is typed in.

### Conventions

- **World axes:** `+X` is image-right, `+Z` is up, the face looks along `−Y`. Lengths are metres.
- **Euler order:** XYZ, world frame, i.e. `R = Rz · Ry · Rx` (rotate about world X, then Y, then Z). Degrees.
- **Reading the angles:** an eye's line of sight is its local `−Y`. `rz > 0` turns the gaze to image-right; `rx < 0` turns it up; `ry` is roll about the line of sight and is always 0 (to float rounding).
- **Eyes:** `L` is `Eye_L`, the subject's own left eye (world `+X`), which the camera sees on the right of the image; `R` is `Eye_R`, on the left of the image. This follows the Blender / Character Creator rig convention.
- **Pixels:** origin at the top-left corner, `x` right, `y` down; the image centre is `(512, 512)`.
- **3D pupil centre:** the centre of the pupil aperture: the mean of the vertices on the open margin of the invisible `Pupil_L` / `Pupil_R` landmark (the iris texture's pupil margin, mapped onto the eyeball through its UVs), transformed to world space. It lies about 17 mm in front of the eyeball centre, so it moves when the eye rotates; the eyeball centre does not.

`metadata/official_sequence.json` keeps the supporting measurements per frame: the 3D pupil and eyeball centres, the quaternions, the full calibration (`K`, `R`, `t`, lens, sensor) the SHA-256 of the rendered PNG, and the path, SHA-256 and centroids of its pupil-mask render (`outputs/pupil_masks/frame_0k.png`).

## Generation

`metadata/metadata_generator.py` converts the Blender measurements into the official records. It raises `ValueError` if a measurement is missing, has the wrong shape, or is NaN or infinite, and writes with `allow_nan=False`, so the file is always standard JSON.

## Validation

`metadata/validator.py` is ordinary Python (standard library only) and recomputes everything independently:

| Area | Checks |
| --- | --- |
| Schema | Ten records; exactly the eight fields; correct shapes; finite numbers only (NaN and Infinity tokens are refused when parsing) |
| Sequence | `frame = k`; `theta`, `h`, `v` equal the formula to 1e-12 |
| Rotations | Angles within ±180°; no roll; the gaze rebuilt from the Euler angles passes through the measured 3D pupil centre and is parallel to the line from the eye midpoint to the fixation target for `(h, v)`, each to 0.01°; `L` and `R` rotations equal to 0.01° (coordinated gaze) |
| Pupils | Inside the image; equal to the 3D pupil centre projected with the record's own camera matrix (0.01 px); `L` to the image-right of `R`; within 0.25 px of the centroid of the pupil drawn in the frame's pupil-mask render; on a dark pupil (darker than the iris below it) in the photoreal frame |
| Camera | `P = K [R | t]`; `fx = fy = lens · width / sensor width`; principal point at the image centre; `R` a rotation; camera 0.400 m from the eye midpoint, which projects to the image centre; identical in every frame |
| Image | `renders/frame_0k.png` and `outputs/pupil_masks/frame_0k.png` exist, are valid 1024 × 1024 8-bit RGB PNGs, and have the SHA-256 recorded when the frame was measured |

The fixation target is rebuilt as eye midpoint + 0.35 m toward the camera + 0.05 m × `(h, v)`.

`outputs/validation_report.json` holds `valid`, the conventions and tolerances, a summary, the camera values, and for every frame and eye the rotation, the gaze errors, the 3D pupil centre, the metadata and rendered 2D centres and their difference. It is written on failure too, with every error listed, and the validator then raises `MetadataValidationError`.

## Measured values (latest run)

| Quantity | Value |
| --- | --- |
| Gaze rebuilt from rotations vs gaze direction | at most 2.2e-05° |
| 2D pupil centre vs projected 3D pupil centre | 0 px |
| 2D pupil centre vs pupil drawn in the mask render | at most 0.023 px, mean 0.015 px, all 20 pupils found |
| Camera distance from eye midpoint | 0.400 m |
| Focal length, principal point | 1991.111 px, (512, 512) |

`tests/test_metadata.py` also confirms that the validator rejects 28 kinds of wrong metadata, including a missing field, a wrong frame number, rounded inputs, a rotation off by 1°, a pupil shifted 3 px, eyeball centres in place of pupil centres, swapped eyes, a changed camera matrix, NaN and Infinity, another frame's image, one eye turned on its own, and another frame's (or a missing) pupil mask.
