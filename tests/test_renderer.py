"""Ordinary-Python acceptance test for ``wrapper.renderer.render``.

    python3 tests/test_renderer.py

Renders the eye pose saved in ``scene.blend`` through the public
wrapper, checks the PNG, checks that the scene file is untouched, and checks
that each kind of failure is reported as ``RenderError`` with a clear reason.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wrapper.blender_runner import blender_executable
from wrapper.renderer import DEFAULT_SCENE, RenderError, png_size, render, render_with_details
sys.path.insert(0, str(ROOT / "tests"))
from test_wrapper import assert_same_image


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expect_error(label: str, fragment: str, call) -> None:
    try:
        call()
    except RenderError as error:
        assert fragment.lower() in str(error).lower(), f"{label}: error does not explain the failure: {error}"
        print(f"FAILURE_REPORTED {label}: {str(error).splitlines()[0]}")
    else:
        raise AssertionError(f"{label}: no RenderError was raised")


def tampered_scene(directory: Path, expression: str) -> Path:
    """Save a copy of the scene with one deliberate change, leaving the original untouched."""
    copy = directory / "tampered.blend"
    script = f"import bpy; {expression}; bpy.ops.wm.save_as_mainfile(filepath={str(copy)!r}, copy=True)"
    subprocess.run([str(blender_executable()), "--background", "--factory-startup", str(DEFAULT_SCENE),
                    "--python-exit-code", "1", "--python-expr", script], check=True, capture_output=True, text=True)
    return copy


def main() -> None:
    scene_before = digest(DEFAULT_SCENE)
    output = ROOT / "renders" / "stage3_wrapper.png"
    output.write_bytes(b"stale")  # a leftover file must be replaced, not trusted

    returned = render(output)
    assert isinstance(returned, Path) and returned == output.resolve(), f"render() returned {returned!r}"
    assert png_size(returned) == (1024, 1024), f"Unexpected size {png_size(returned)}"
    assert returned.stat().st_size > 10_000, "Render is implausibly small"

    # Same pose, same camera, same lighting: a second render must be the same image.
    second_path, details = render_with_details(ROOT / "renders" / "stage3_wrapper_repeat.png")
    assert details["camera_fixed"] is True and details["lighting_constant"] is True
    assert details["resolution_px"] == [1024, 1024]
    assert set(details["pupil_center_2D"]) == {"L", "R"}
    assert_same_image(second_path, returned, "Two renders of the same pose differ")
    assert digest(DEFAULT_SCENE) == scene_before, "Rendering modified scene.blend"
    print(f"RENDER_OK path={returned} size=1024x1024 repeatable=true scene_untouched=true")

    expect_error("non-PNG output", ".png", lambda: render(ROOT / "renders" / "frame.jpg"))
    expect_error("missing scene", "not found", lambda: render(output, scene=ROOT / "blender" / "missing.blend"))
    expect_error("timeout", "did not finish", lambda: render(output, timeout=0.001))
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        moved = tampered_scene(directory, "bpy.context.scene.camera.location.y -= 0.05")
        expect_error("moved camera", "camera distance", lambda: render(directory / "moved.png", scene=moved))
        assert not (directory / "moved.png").exists(), "An image was written despite a moved camera"
        relit = tampered_scene(directory, "bpy.data.objects['KeyLight'].data.energy *= 3")
        expect_error("changed lighting", "lighting", lambda: render(directory / "relit.png", scene=relit))
        zoomed = tampered_scene(directory, "bpy.context.scene.camera.data.lens = 85")
        expect_error("changed lens", "lens", lambda: render(directory / "zoomed.png", scene=zoomed))

    # The timeout case removes the stale output before starting; restore a good image.
    render(output)
    assert_same_image(output, second_path, "The restored render differs from the first")
    assert digest(DEFAULT_SCENE) == scene_before, "A failed render modified scene.blend"
    print("RENDERER_TEST_OK")


if __name__ == "__main__":
    main()
