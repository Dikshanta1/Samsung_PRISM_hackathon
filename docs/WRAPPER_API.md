# External Python Wrapper (Stage 4)

`wrapper.eyes.Eyes` is the evaluator-facing API. It runs under ordinary system Python and never imports `bpy`.

```python
from wrapper.eyes import Eyes

eyes = Eyes()
eyes.move(1, 0)          # look image-right
eyes.render()            # -> outputs/eye_render_0001.png (a pathlib.Path)
eyes.reset()
```

Run it from the project root, or put the project root on `PYTHONPATH`.

## How it talks to Blender

`bpy` only works inside Blender's own Python, so every call starts Blender in background mode:

```text
Blender --background --factory-startup blender/scene.blend --python-exit-code 1 \
    --python scripts/blender_worker.py -- <move|reset|render> --h=H --v=V [--output FILE.png]
```

`scripts/blender_worker.py` runs inside Blender. It confirms that the intended file was loaded and that it is the eye scene, checks the locked camera and lighting, sets the fixation with `blender/calibration.py`, measures the result, renders if asked, and prints one line (`WORKER_RESULT {json}` or `WORKER_ERROR reason`) that the wrapper parses. Each Blender process exits when its command is done; none is left running.

Blender is located through the `BLENDER_BIN` environment variable, then `blender` on `PATH`, then `/Applications/Blender.app/Contents/MacOS/Blender`.

**The scene file is never saved.** The current `(h, v)` is held by the `Eyes` object and sent with every command as an absolute pose. `blender/scene.blend` therefore always contains the neutral pose, the locked camera and the constant lighting, and cannot be damaged by an interrupted run. Consequences:

- Movements cannot accumulate: the pose depends only on the last `move` or `reset`.
- A new `Eyes()` object starts at neutral `(0, 0)`. The pose does not carry over between Python processes.

## API

### `Eyes(output_dir=None, *, scene=None, timeout=600.0)`

| Argument | Meaning |
| --- | --- |
| `output_dir` | Directory for rendered images. Default `outputs/` in the project. Created when needed. |
| `scene` | Another `.blend` file to control. Default `blender/scene.blend`. Raises `FileNotFoundError` if missing. |
| `timeout` | Limit in seconds for each Blender run. |

### `move(h, v) -> dict`

Fixates both eyes on the target for normalised inputs in `[-1, +1]`: `h = +1` is image-right, `v = +1` is up (±5 cm at the 35 cm target plane). Values outside the range, NaN, infinities and non-numbers raise `ValueError` before Blender is started, and the current pose is kept.

Returns what Blender measured:

| Key | Content |
| --- | --- |
| `inputs` | `{"h", "v"}` as applied |
| `fixation_target_world_m` | Target position `[x, y, z]` |
| `angular_error_degrees` | Per eye, angle between the measured gaze and the target direction |
| `convergence` | `ray_miss_m`, `vergence_point_error_m` |
| `eye_rotation_euler_xyz_degrees` | Per eye, world-frame `[rx, ry, rz]` |
| `world_eye_rotations_quaternion` | Per eye, world-frame `[w, x, y, z]` |
| `pupil_center_2D` | Per eye, `[u, v]` pixels (origin top-left, `v` down) |
| `camera_matrix` | 3 × 4 projection matrix `P = K [R | t]` |
| `camera_fixed`, `lighting_constant` | `true`; the command fails otherwise |
| `scene`, `blender_version` | The file Blender loaded and the Blender version |

`L` is `Eye_L`, the subject's own left eye (world `+X`), which the camera sees on the right of the image; `R` is `Eye_R`, on the left of the image. This follows the Blender / MakeHuman rig convention.

### `reset() -> dict`

Returns both eyes to the calibrated neutral pose, `(0, 0)`, and returns the same report. It sets the pose directly; it does not undo earlier movements.

### `render(output_path=None) -> pathlib.Path`

Renders the current pose to a 1024 × 1024 8-bit RGB PNG and returns its absolute path.

| `output_path` | Image written to |
| --- | --- |
| omitted | `output_dir/eye_render_0001.png`, `…0002.png`, … (counted per `Eyes` object) |
| relative | `output_dir/<output_path>` |
| absolute | exactly that path |

Missing folders are created and an existing file is replaced. Blender's report for the frame (same keys as `move`, plus `output`) is kept in `eyes.last_render`.

### `position`

The current `(h, v)` tuple.

### Errors

| Exception | When |
| --- | --- |
| `ValueError` | `h` or `v` is not a finite number in `[-1, +1]` |
| `FileNotFoundError` | The scene file does not exist |
| `BlenderWorkerError` | Blender cannot be found or started, times out, loads a file that is not the eye scene, finds the camera or lighting changed, fails to render, or produces something that is not a 1024 × 1024 PNG |

`BlenderWorkerError` carries the reason on its first line, followed by the tail of Blender's output.

## Lower-level renderer

`wrapper.renderer.render(path)` renders the pose saved in the scene file (neutral). `render(path, pose=(h, v))` applies a pose first; this is what `Eyes.render` uses. See `docs/CAMERA_CALIBRATION.md`.

## Dataset script

```bash
python3 scripts/generate_dataset.py --output-dir outputs/demo --pose=-1,0 --pose=0,1
```

Each `--pose=H,V` becomes `frame_NNNN.png` in the output directory. `dataset.json` lists, per frame, the input, image name, eye rotations, 2D pupil centres and camera matrix. The script renders only the poses it is given; it does not run the official ten-frame sequence.

## Test

```bash
python3 tests/test_wrapper.py
```

Runs under system Python against the real `blender/scene.blend`, with no mocks, and takes about 45 seconds. It checks that:

- Blender launches and reports loading `blender/scene.blend`;
- out-of-range and non-numeric inputs are rejected and leave the pose unchanged;
- left, right, up and down each move both pupils at least 10 px the commanded way, on target to 0.001°;
- repeating a move, or reaching it by a different route, gives the identical pose, and `reset()` gives the identical neutral pose;
- renders are valid 1024 × 1024 PNGs; the pupil found in the decoded pixels is within 2 px of the reported centre and moves left and right; the forehead region is pixel-identical;
- the render after `reset()` is byte-identical to the first neutral render and to a render of the saved scene;
- default, relative and absolute output paths and two separate output directories work;
- a missing scene, a non-PNG path, a timeout and a wrong `.blend` file are each reported;
- `blender/scene.blend` is byte-identical afterwards.
