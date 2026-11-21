# Eye Movement Calibration

The eye midpoint (the cyclopean eye, halfway between the two eyeball rotation centres) is `(0, -0.0265, 1.7216)` m. Forward is world `-Y`, so the neutral target is `(0, -0.3765, 1.7216)`: exactly 0.350 m forward.

`move(h, v)` requires both normalized inputs in `[-1, +1]` and uses this explicit, bounded mapping:

```text
target = eye_midpoint + (0.050 * h, -0.350, 0.050 * v)
```

## Coordinated gaze

The two eyes always move together. There is one gaze direction for the whole face:

```text
direction = normalize(target - eye_midpoint)
```

Both eyes are rotated about their own centres so that their optical axes are parallel to it. `direction.to_track_quat("-Y", "Z")` gives the world rotation (local `-Y` is the optical axis, no roll). The same quaternion is applied to `EyeBone_L` and `EyeBone_R`, each converted to its bone's rest space and written as an absolute pose-bone basis.

| Input | Both eyes |
| --- | --- |
| `(0, 0)` (neutral) | straight ahead, rotation `(0, 0, 0)` |
| `(+1, 0)` | right by `atan(5/35)` = 8.13° |
| `(-1, 0)` | left by 8.13° |
| `(0, +1)` | up by 8.13° |
| `(0, -1)` | down by 8.13° |
| diagonals | the matching combination, e.g. `(0.951, 0.309)`: 7.74° right and 2.50° up |

So the eyes never cross or drift apart, and each input moves both pupils by the same amount (about 12 px at full range).

Why not converge on the target? An earlier version aimed each eye separately at the 35 cm target, which is near-field vergence. It made the neutral pose cross-eyed (each eye turned 5.45° inward). For a sideways target it also made one eye turn 13° while the other stayed almost straight (2.3°): geometrically correct for a target that close, but it reads as uncoordinated eyes. The target still defines the gaze direction exactly; only the vergence is removed.

## Lids

The eyelids follow the gaze (`blender/eyelids.py`): looking up raises the upper lid, looking down lowers it. Only the lids move; the eyeballs and pupils are unaffected.

## Reset and measurement

`reset()` calls `move(0, 0)`, recalculating the neutral pose directly. It never reverses an incremental rotation, and `build_scene.py` saves `scene.blend` in this pose.

Eye centres are read from the rig (`rig.matrix_world @ bone.head_local`), not from constants, and the pose is written as rotation only. Accuracy is measured from the posed scene. The gaze ray runs from each eyeball's world centre through its pupil landmark. `angular_error_degrees` is the angle between that ray and the shared gaze direction. `binocular_alignment` reports the angle between the two eyes' rays and the rotation difference between the eyeballs; both are 0 to float precision.

The camera sits 0.400 m forward of the eye midpoint with its optical axis through that midpoint, so the midpoint projects to pixel (512, 512).

```python
from wrapper.eyes import Eyes
eyes = Eyes()
eyes.move(-1.0, 0.0)
eyes.reset()
```

The wrapper returns Blender-measured target coordinates, eye rotations, and angular errors. It never saves `scene.blend`; see `docs/WRAPPER_API.md`.
