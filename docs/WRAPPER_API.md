# External Python Wrapper

`wrapper.eyes.Eyes` is the evaluator-facing API. It is ordinary Python and never imports `bpy`. Each `move` or `reset` starts Blender in background mode, loads the actual `blender/scene.blend`, and runs `scripts/blender_worker.py` inside Blender's own Python runtime. `render` uses the same saved scene through the locked renderer.

```python
from wrapper.eyes import Eyes

eyes = Eyes(output_dir="outputs/evaluation")
eyes.move(1.0, 0.0)
image = eyes.render()             # outputs/evaluation/eye_render_0001.png
eyes.reset()
```

## Methods

- `move(h, v)`: validates inclusive normalized inputs `[-1, +1]`, saves an absolute binocular fixation pose, and returns Blender-measured pose data including angular error.
- `reset()`: saves the calibrated `(0, 0)` fixation pose and returns the same report format.
- `render(output_path=None)`: generates a real 1024 × 1024 PNG from the current saved pose and returns an absolute `Path`. A relative path is resolved below `output_dir`.

`Eyes` locates Blender with `BLENDER_BIN`, then `blender` on `PATH`, then the verified macOS application path. Blender failures, timeouts, and malformed worker output raise `BlenderWorkerError` with the useful tail of the Blender log. Render failures are translated into the same exception type.

## CLI helper

`scripts/generate_dataset.py` only renders poses explicitly supplied by the caller; it intentionally does not initiate the official ten-frame sequence.

```bash
python3 scripts/generate_dataset.py --output-dir outputs/demo --pose=-1,0 --pose=0,1
```
