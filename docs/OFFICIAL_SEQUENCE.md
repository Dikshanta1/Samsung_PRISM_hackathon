# Official Ten-Direction Clockwise Sequence

Run the entire Stage 5A pipeline from the repository root:

```bash
python3 scripts/generate_official_sequence.py
```

For every integer `k` from 0 through 9, the generator evaluates, without manually rounded inputs:

```text
theta = 2*pi*k/10
h = sin(theta)
v = cos(theta)
```

The labels are ordered `Top`, `Upper-right`, `Right-upper`, `Right-lower`, `Lower-right`, `Bottom`, `Lower-left`, `Left-lower`, `Left-upper`, and `Upper-left`.

Clockwise is as seen in the image: `h = +1` is image-right and `v = +1` is up.

## What one run does

1. Deletes any earlier `renders/frame_*.png`, `metadata/frame_*.json`, `metadata/official_sequence.json`, `metadata.json` and `outputs/contact_sheet.png`, so no previous image can be reused.
2. For each `k`, calls `Eyes.move(h, v)` and `Eyes.render()` on the real `scene.blend` and writes `renders/frame_00.png` to `renders/frame_09.png` (1024 × 1024, 8-bit RGB).
3. Writes `metadata/frame_00.json` to `frame_09.json` and the combined `metadata/official_sequence.json`. Every value is either computed from the formula or reported by the Blender process that rendered the frame: `frame`, `direction`, `theta_radians`, `inputs` (`h`, `v` at full double precision), `image`, world-frame eye rotations (quaternion and XYZ Euler degrees), `pupil_center_2D`, `camera_matrix`, the full `camera_calibration`, `angular_error_degrees` and `binocular_alignment`.
4. Writes the official `metadata.json` at the project root (see below).
5. Builds `outputs/contact_sheet.png` (3430 × 1728): the ten frames in order, five per row, each labelled with its frame number, direction, `h` and `v`.
6. Runs the acceptance check below and exits with an error if any part fails.

A run takes about 35 seconds.

## Official `metadata.json`

A JSON array with one record per render, in frame order, each with exactly these keys:

| Key | Value |
| --- | --- |
| `frame` | `k`, 0 to 9 |
| `theta` | `2πk/10` in radians, full double precision |
| `input` | `{"h": sin θ, "v": cos θ}`, full double precision |
| `eye_rotation_L`, `eye_rotation_R` | `[rx, ry, rz]`: world-frame XYZ Euler angles of the eyeball, in degrees, read from the posed object |
| `pupil_center_2D_L`, `pupil_center_2D_R` | `[x, y]` in pixels: origin at the top-left corner, `x` right, `y` down |
| `camera_matrix` | 3 × 4 projection matrix `P = K [R | t]`, world metres to pixels; identical in every record |

World axes are `+X` image-right, `+Z` up, and the face looks along `−Y`. A gaze to image-right is therefore a positive `rz`, and a gaze upward a negative `rx` (the eye looks along its local `−Y`). `L` is `Eye_L`, the subject's own left eye (world `+X`), which the camera sees on the right of the image; `R` is `Eye_R`, on the left of the image. This follows the Blender / Character Creator rig convention. The same values, with more detail, are in `metadata/official_sequence.json`.

## Acceptance check

```bash
python3 tests/test_official_sequence.py
```

Verifies the generated files (the generator runs the same check on its own output):

- exactly `frame_00.png` to `frame_09.png` exist, each a valid 1024 × 1024 8-bit RGB PNG, and no two are the same image;
- `metadata.json` holds ten records with exactly the eight official keys, matching the detailed metadata, and each `eye_rotation` gives the same gaze direction as the separately recorded quaternion;
- `theta`, `h` and `v` in the metadata equal the formula bit for bit, with the labels above;
- the pupil found in each image's decoded pixels is within 2 px of the recorded `pupil_center_2D`;
- measured in those pixels, each pupil is displaced at least 10 px at clock angle `36k°` (within 8°), which also fixes the order as clockwise from the top;
- the camera matrix and calibration are identical in every frame, the camera is 0.400 m from the eye midpoint, and the forehead region is pixel-identical across frames.

Measured in the latest run, `Eye_L` pupil clock angle and displacement per frame: 1°, 35°, 71°, 108°, 145°, 179°, 216°, 252°, 287°, 323°, each 15.6 to 16.1 px.

The frames, metadata and contact sheet are generated artifacts and are ignored by git; rerun the command to recreate them.
