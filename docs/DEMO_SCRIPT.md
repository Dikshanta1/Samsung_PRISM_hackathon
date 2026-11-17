# Demo Script (about 1 minute 45 seconds)

A technical walkthrough for the demo video. Record a terminal and an image viewer side by side, starting in the bundle's top folder. Spoken lines are in quotes; times are cumulative.

## Before recording

```bash
python3 scripts/generate_official_sequence.py   # so the frames and contact sheet are fresh
rm -rf outputs/demo
```

Have `outputs/contact_sheet.png` and `metadata.json` ready to open.

## 0:00 to 0:15 — What it is

Show: `scene.blend` open in Blender, camera view (Numpad 0), then select `EyeRig` to show the two eye bones.

> "This is our Track 1 entry: a Blender scene with two independently rigged eyes, a camera locked 40 centimetres from the face, and a Python wrapper that moves the eyes and renders ground-truth images."

## 0:15 to 0:45 — The Python interface

Show: terminal. Type and run:

```bash
python3 - <<'EOF'
from wrapper.eyes import Eyes
eyes = Eyes("outputs/demo")
state = eyes.move(1, 0)
print(state["pupil_center_2D"], state["angular_error_degrees"])
print(eyes.render("right.png"))
eyes.move(-1, 0); print(eyes.render("left.png"))
eyes.reset();     print(eyes.render("centre.png"))
EOF
```

> "The wrapper is ordinary Python. Each call starts Blender in the background, because Blender's API only runs inside Blender. `move` takes normalised inputs from minus one to plus one and aims both eyes at one target 35 centimetres away, so they converge. It returns what Blender measured: the pupil positions in pixels, and an aiming error of zero degrees."

Show: `outputs/demo/left.png`, `centre.png`, `right.png` one after another.

> "Left, centre, right. Poses are absolute, so nothing accumulates, and the scene file is never modified."

## 0:45 to 1:10 — The ten official frames

Show: terminal.

```bash
python3 scripts/generate_official_sequence.py
```

> "One command produces the official sequence: ten directions, clockwise from the top, with h as the sine and v as the cosine of the angle."

Show: `outputs/contact_sheet.png` full screen; trace the gaze around the circle with the cursor.

> "Top, upper right, right, and round to upper left. The command also checks its own output: it finds each pupil in the rendered pixels and confirms it sits at the right clock angle."

## 1:10 to 1:30 — Ground truth

Show: `metadata.json`, first record.

> "Every frame has a metadata record: the inputs, each eye's world rotation, the 2D pupil centres, and the camera matrix. All of it is read from the Blender process that rendered the frame. The pupil centre comes from the pupil mesh itself and is projected through the calibrated camera."

Show: terminal.

```bash
python3 metadata/validator.py
```

> "An independent validator rebuilds the gaze from the rotations, reprojects the pupils, and compares them with the actual pixels. The worst difference is two thirds of a pixel."

## 1:30 to 1:45 — Reproducibility and limits

Show: `outputs/final_validation_report.json`, the `"passed": true` line and the clean-extract section.

> "The packaging command runs every test, builds the ZIP, then unpacks it into an empty folder and runs everything again. The regenerated frames are byte-identical to the ones shipped. The main limitation is the face: it is a procedural stand-in, not yet a textured MakeHuman head. The rig, calibration, wrapper and metadata are complete and verified."

## Figures to quote if asked

| Fact | Value |
| --- | --- |
| Fixation target | 35 cm from the eye midpoint, ±5 cm |
| Camera | 40 cm, 40 mm lens, focal length 1137.78 px, principal point (512, 512) |
| Output | 1024 × 1024 8-bit RGB PNG, EEVEE, constant lighting |
| Pupil shift at full range | about 16 px |
| Gaze error (rotation vs target) | under 0.00001° |
| Metadata vs rendered pupil | at most 0.67 px, mean 0.27 px |
| Time | about 1.5 s per move, 2 s per render, 35 s for the ten frames |
