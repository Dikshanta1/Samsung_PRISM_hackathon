#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$project_root/wrapper/blender_runner.py"
python3 "$project_root/tests/verify_png.py" "$project_root/renders/smoke_test.png"
