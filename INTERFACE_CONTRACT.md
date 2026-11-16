# Interface Contract

The Stage 1 public interface will be exposed as Python methods from an ordinary-Python wrapper:

```python
eyes.move(h: float, v: float) -> None
eyes.reset() -> None
eyes.render() -> Path
```

`h` and `v` are inclusive normalized values in `[-1.0, +1.0]`; other values raise `ValueError`. `reset()` sets both physical eyeball rotations to the calibrated neutral pose. `render()` invokes Blender in background mode and returns a path to an actual 1024 × 1024 PNG, with a JSON frame sidecar in `metadata/`.

Stage 1 will map the normalized values to rotations about separate left/right eye centres and record input values, world eye rotations, 2D pupil centres, and the camera matrix in the sidecar.
