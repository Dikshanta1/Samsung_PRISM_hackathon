# Architecture

## Stage 0 boundary

`blender/` contains code that imports `bpy` and is only executed by Blender. `wrapper/` contains normal CPython orchestration, which starts Blender in background mode through `subprocess`. `tests/` contains dependency-free verification that can run in ordinary Python.

## Planned modular layout

- `blender/scene/`: face, eye, rig, lighting, and camera builders.
- `blender/animation/`: normalized gaze to physical eye rotations.
- `blender/rendering/`: 1024 px render configuration and image-plane projection.
- `wrapper/`: command-line orchestration and batch rendering.
- `metadata/`: per-frame JSON sidecars.
- `assets/`: externally acquired, licensed source assets only.

This separation keeps `bpy` out of the normal Python environment and keeps rendering repeatable in Blender background mode.
