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

Each pass uses the real `Eyes` wrapper, renders a fresh `renders/frame_00.png` through `renders/frame_09.png`, validates that PNG as 1024 × 1024, and writes generated Blender-measured JSON to `metadata/frame_00.json` through `metadata/frame_09.json`. The JSON includes formula inputs, world eye rotations, projected pupil centres, the camera projection matrix, and the full camera calibration derived from the active scene camera.

The command also creates `outputs/contact_sheet.png` with every numbered frame and direction label. It fails if camera/lighting locking or output validation fails.
