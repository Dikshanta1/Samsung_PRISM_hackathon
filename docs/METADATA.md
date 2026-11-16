# Ground-Truth Metadata

Generate fresh metadata and validation output with:

```bash
python3 tests/test_metadata.py
```

`metadata/metadata_generator.py` first runs the official real-Blender sequence, then produces the official root-level `metadata.json` as a list of ten records. Frame `k` is associated exactly with `renders/frame_kk.png`. The generated sequence manifest retains the actual 3D pupil landmarks and full camera calibration as provenance.

`eye_rotation_L` and `eye_rotation_R` are actual world-space Blender Euler rotations in intrinsic `XYZ` order, in **degrees**. Pupil 3D points (in the provenance manifest) are the local `-Y` front apex of each pupil geometry, transformed to world metres. `pupil_center_2D_*` is that landmark projected through the active calibrated Blender camera. `camera_matrix` is the actual 3×4 projection matrix `P = K [R | t]` derived from the active camera.

The validator rejects absent fields, wrong formula values, out-of-range image properties, malformed matrices, missing images, NaN/infinite values, and camera changes. It decodes each actual RGB PNG and measures its dark pupil blob, requiring agreement with the projected pupil centre.
