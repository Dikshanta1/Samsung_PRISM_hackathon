# Eye Movement Calibration

The eye midpoint is `(0, -0.133, 0.055)` m. Forward is world `-Y`, making the neutral target `(0, -0.483, 0.055)`: exactly 0.350 m forward.

`move(h, v)` requires both normalized inputs in `[-1, +1]` and uses this explicit, bounded mapping:

```text
target.x = 0.050 * h
target.y = -0.483
target.z = 0.055 + 0.050 * v
```

This maps horizontal and vertical input to lateral and vertical target offsets of ±5 cm; it does not use arbitrary eye angles. For each eye, `direction = normalize(target - eye_centre)`. `direction.to_track_quat("-Y", "Z")` supplies the Blender world quaternion for the model's local `-Y` optical axis. That quaternion is converted to each bone's rest coordinate space and applied as an absolute pose-bone basis matrix.

`reset()` calls `move(0, 0)`, recalculating the neutral pose directly. It never reverses an incremental rotation.

The calibrated neutral is therefore the converged pose (each eye turned 10.68° inward), and `build_scene.py` saves `scene.blend` in it. `eye_rig.zero_pose()` is different: it zeroes the bone rotations for parallel, straight-ahead gaze and is only used by rig-level tests.

Eye centres are read from the rig (`rig.matrix_world @ bone.head_local`), not from constants, and the pose is written as rotation only. Angular error and convergence are measured from the posed scene: the gaze ray runs from each eyeball's world centre through its pupil's world centre, and `convergence` reports how far the two rays miss each other and how far their meeting point is from the target.

The camera sits 0.400 m forward of the eye midpoint with its optical axis through that midpoint, so the midpoint projects to pixel (512, 512).

```python
from wrapper.eye_controller import EyeController
eyes = EyeController()
eyes.move(-1.0, 0.0)
eyes.reset()
```

The wrapper returns Blender-measured target coordinates, eye quaternions, and angular errors.
It persists `move`/`reset` to `blender/scene.blend`; the acceptance test itself leaves the tracked scene in reset pose.
