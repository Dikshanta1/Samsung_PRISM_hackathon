# Stage 1 Asset and Rig Report

## Asset investigation and fallback

The preferred source was MPFB 2.0.18 from the official Blender Extensions platform (GPL-3.0-or-later). It supports Blender 4.2+ and offers generated human meshes, procedural skin materials, and eye materials. On 2026-11-16, this Blender installation had no MPFB extension and its official-catalog synchronization was blocked by the disabled persistent “online access” security preference. The preference was not changed automatically.

Accordingly, this scene uses a **procedural fallback**, generated entirely by `blender/build_scene.py`. It is recognizable as a human face but does not contain photographic/image skin texture. This is an acknowledged visual limitation against the official textured-face requirement. No third-party face asset is embedded or redistributed.

References: [official MPFB extension](https://extensions.blender.org/add-ons/mpfb/) (GPL-3.0-or-later) and [MPFB getting started guide](https://static.makehumancommunity.org/mpfb/docs/getting_started.html).

## Scene hierarchy

`EyeRig` is an armature with `EyeBone_L` and `EyeBone_R`. `Eye_L` and `Eye_R` are separate spherical sclera meshes parented to their respective bones. `Iris_L`/`Pupil_L` are children of `Eye_L`; their right counterparts are children of `Eye_R`. `HumanHead`, sockets, facial features, `Camera`, and `FixationTarget` are separate scene objects.

## Eye centres and bone configuration

| Side | Object / bone | World centre (m) | Bone tail (m) |
| --- | --- | --- | --- |
| Left (subject's left, image-right) | `Eye_L` / `EyeBone_L` | `(0.066, -0.133, 0.055)` | `(0.066, -0.133, 0.100)` |
| Right (subject's right, image-left) | `Eye_R` / `EyeBone_R` | `(-0.066, -0.133, 0.055)` | `(-0.066, -0.133, 0.100)` |

Each bone head equals its eye sphere origin. Eye rotations are applied to the pose bones; the eye sphere, iris, and pupil therefore rotate about the physical eye centre with no flat 2D translation.

The bones point along world +Z, so bone-local X is the pitch axis, bone-local Y (world Z) is the yaw axis, and bone-local Z is the line of sight (never rotated — that would only twist the eye). `set_eye_rotation(rig, side, pitch, yaw)` uses `pitch > 0` = look up and `yaw > 0` = look toward world +X (image-right). `Eye_L` is the subject's own left eye at world +X (image-right) and `Eye_R` is at world −X (image-left), following the Blender / MakeHuman rig convention. `tests/test_eye_rig.py` projects each pupil through the camera and asserts Up, Down, Left, Right and Reset for both eyes independently.

## Fixed target, camera, renders, and commands

`FixationTarget` is at `(0, -0.483, 0.055)`, exactly 0.350 m in front of the eye midpoint. `Camera` is at `(0, -0.533, 0.055)`, exactly 0.400 m in front of that midpoint, and faces the head. Lighting is fixed before all three 1024 × 1024 PNG renders. Since Stage 3 the camera and lighting are created by `blender/camera_setup.py` and `blender/lighting_setup.py` and rendered with EEVEE; see `docs/CAMERA_CALIBRATION.md`.

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --python blender/build_scene.py -- "$PWD/renders"
/Applications/Blender.app/Contents/MacOS/Blender --background scene.blend --python tests/test_eye_rig.py
python3 tests/verify_png.py renders/stage1_front.png
```

The build writes `renders/stage1_front.png`, `renders/stage1_left_eye_rotation.png`, and `renders/stage1_right_eye_rotation.png` and saves `scene.blend` in neutral pose.
