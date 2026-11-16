"""Blender-runtime command worker used by :mod:`wrapper.eyes`.

This file must be run by Blender, never ordinary CPython.  It loads the scene
already supplied on Blender's command line, performs one absolute eye pose,
optionally persists it, and emits one machine-readable result line.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))
from calibration import state

RESULT_PREFIX = "WORKER_RESULT "
ERROR_PREFIX = "WORKER_ERROR "


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("move", "reset"))
    parser.add_argument("--h", type=float, default=0.0)
    parser.add_argument("--v", type=float, default=0.0)
    parser.add_argument("--save", action="store_true")
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(arguments)
    try:
        result = state(0.0, 0.0) if args.action == "reset" else state(args.h, args.v)
        if args.save:
            bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    except Exception as error:
        print(f"{ERROR_PREFIX}{type(error).__name__}: {error}", flush=True)
        raise
    print(RESULT_PREFIX + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
