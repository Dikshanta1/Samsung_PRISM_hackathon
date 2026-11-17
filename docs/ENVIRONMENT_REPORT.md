# Environment Report — Stage 0

Checked on 2026-11-16 (Asia/Kolkata).

| Check | Result |
| --- | --- |
| Operating system | macOS 27.2.1, Apple Silicon (`arm64`) |
| Python | CPython 3.14.0 (`python3`) |
| Git | Available: 2.54.0 (`/usr/bin/git`) |
| Blender installed | Yes |
| Blender version | 5.3.0, build `02f0899d78e3` (2026-11-10) |
| Blender executable | `/Applications/Blender.app/Contents/MacOS/Blender` |
| Background mode | Supported; `--background` completed successfully |
| `bpy` script execution | Supported; reported `BPY_OK=5.3.0` and `BACKGROUND=True` |
| Free project-volume space | 258 GiB at inspection |
| MPFB/MakeHuman assets | Obtainable; see below |

## Asset recommendation

Use MPFB 2 from Blender’s Extensions platform rather than MakeHuman desktop. MPFB is an open-source human generator for Blender and requires Blender 4.2+, so it is compatible with the installed Blender 5.3. Install the MPFB extension and the MakeHuman system-assets pack before Stage 1; keep downloaded archives and license/source notes under `assets/`.

Official references: [MPFB downloads](https://static.makehumancommunity.org/mpfb/downloads.html), [MPFB source and compatibility](https://github.com/makehumancommunity/mpfb2), and [MakeHuman releases](https://static.makehumancommunity.org/makehuman/releases.html). No asset was installed during Stage 0, so the source face remains an explicit Stage 1 prerequisite.

## Reproducible Blender selection

The wrapper resolves `BLENDER_BIN` first, then a `blender` command on `PATH`, then the verified application binary above. For another machine, install the current Blender release from [blender.org/download](https://www.blender.org/download/) and set `BLENDER_BIN` to its executable path.
