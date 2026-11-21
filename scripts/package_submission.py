"""Final validation and packaging of the Track 1 submission, in one command.

    python3 scripts/package_submission.py --team-name TEAM

1. Runs the final tests in this project, regenerating the ten frames,
   ``metadata.json``, the contact sheet and the metadata validation report.
2. Builds ``dist/TEAM.zip`` with the required layout (``scene.blend``,
   ``wrapper/eyes.py``, ``renders/frame_00..09.png``, ``metadata.json``,
   ``README.md``) plus the sources needed to reproduce everything.
3. Re-opens the ZIP and checks its integrity and contents.
4. Extracts the ZIP into an empty temporary folder and runs the same final
   tests there, so the package is proven to work on its own.
5. Writes ``outputs/final_validation_report.json``.

Exits with a non-zero status if any step fails.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wrapper.blender_runner import blender_executable
sys.path.insert(0, str(ROOT / "tests"))
from test_wrapper import SAME_IMAGE_MAX_LEVELS, SAME_IMAGE_MAX_PIXELS, image_difference

DIST = ROOT / "dist"
REPORT = ROOT / "outputs" / "final_validation_report.json"
FRAMES = [f"renders/frame_{k:02d}.png" for k in range(10)]
REQUIRED = ["scene.blend", "wrapper/eyes.py", "metadata.json", "README.md", *FRAMES]
SOURCE_DIRECTORIES = ("blender", "wrapper", "scripts", "tests", "metadata", "docs", "assets")
ROOT_FILES = ("scene.blend", "metadata.json", "README.md", "requirements.txt")
GENERATED = ("outputs/contact_sheet.png", "outputs/validation_report.json",
             *(f"outputs/pupil_masks/frame_{k:02d}.png" for k in range(10)))
SOURCE_SUFFIXES = {".py", ".md", ".sh", ".txt"}
FORBIDDEN = ("__pycache__", ".DS_Store", ".blend1", ".pyc", ".git/")
LIMITATIONS = [
    "The head is a third-party Character Creator 3 character (Hassan V1), not one of the listed open assets; its "
    "licence for redistribution has not been verified.",
    "Materials whose auxiliary maps were missing from the source were rebuilt from the embedded diffuse, normal and "
    "opacity maps; the CC3 iris brightness and sclera tint are recreated with UV masks.",
    "The head is life-size (66.8 mm between eye centres), so the full +-5 cm range turns each eye about 8 degrees "
    "and moves each pupil about 12 px.",
    "The cornea does not refract; hair cards cast no shadows (their dithered shadows were not reproducible).",
    "Only Blender 5.3.0 on macOS (Apple Silicon) was tested. Renders are reproducible to within 2 levels on at most "
    "64 pixels; other Blender versions or GPUs may differ slightly.",
    "Each wrapper call starts a new Blender process (about 2 s per move, 3 s per render).",
    "Inputs are a square range: h and v are each limited to [-1, +1], so a corner such as (1, 1) places the target "
    "7.07 cm from centre. The official ten-frame circle stays within 5 cm.",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def final_tests(root: Path) -> list[dict]:
    """Run the final tests with ``root`` as the project. Outputs are regenerated, never reused."""
    blender = str(blender_executable())
    in_blender = [blender, "--background", "--factory-startup", "scene.blend", "--python-exit-code", "1", "--python"]
    steps = (
        ("scene_loading", in_blender + ["tests/test_eye_rig.py"]),
        ("five_direction", in_blender + ["tests/test_directions.py"]),
        ("camera_calibration", in_blender + ["tests/test_camera.py"]),
        ("python_wrapper", [sys.executable, "tests/test_wrapper.py"]),
        ("ten_frame_generation_and_metadata_validation", [sys.executable, "tests/test_metadata.py"]),
    )
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    results = []
    for name, command in steps:
        started = time.time()
        completed = subprocess.run(command, cwd=root, env=environment, text=True, capture_output=True)
        log = completed.stdout + "\n" + completed.stderr
        confirmations = [line.strip() for line in log.splitlines() if re.search(r"_OK\b", line) and not line.startswith("FRAME_OK")]
        passed = completed.returncode == 0 and bool(confirmations)
        results.append({"name": name, "passed": passed, "seconds": round(time.time() - started, 1),
                        "command": " ".join(command[:1] and [Path(command[0]).name] + command[1:]),
                        "result": confirmations[-1] if confirmations else None,
                        "confirmations": confirmations,
                        "output_tail": None if passed else "\n".join(log.strip().splitlines()[-25:])})
        print(f"  {'PASS' if passed else 'FAIL'} {name} ({results[-1]['seconds']} s)", flush=True)
        if not passed:
            break  # later steps depend on earlier ones
    return results


def package_files() -> list[str]:
    """Project-relative paths that go into the ZIP, in a stable order."""
    files = [name for name in ROOT_FILES]
    for directory in SOURCE_DIRECTORIES:
        for path in sorted((ROOT / directory).rglob("*")):
            relative = path.relative_to(ROOT).as_posix()
            if path.is_file() and path.suffix in SOURCE_SUFFIXES and not any(marker in relative for marker in FORBIDDEN):
                files.append(relative)
    files += FRAMES + list(GENERATED)
    missing = [name for name in files if not (ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Cannot package: missing {missing}")
    return files


def build_zip(team_name: str) -> Path:
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"{team_name}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in package_files():
            bundle.write(ROOT / name, name)
    return archive


def check_zip(archive: Path) -> dict:
    """Re-open the archive and verify its integrity and contents against the project files."""
    problems = []
    with zipfile.ZipFile(archive) as bundle:
        corrupt = bundle.testzip()
        if corrupt:
            problems.append(f"corrupt entry {corrupt}")
        names = bundle.namelist()
        problems += [f"missing required file {name}" for name in REQUIRED if name not in names]
        renders = sorted(name for name in names if name.startswith("renders/"))
        if renders != FRAMES:
            problems.append(f"renders/ must hold exactly the ten frames, found {renders}")
        problems += [f"unwanted entry {name}" for name in names if any(marker in name for marker in FORBIDDEN)]
        problems += [f"unsafe path {name}" for name in names if name.startswith("/") or ".." in Path(name).parts]
        if len(names) != len(set(names)):
            problems.append("duplicate entries")
        for name in names:
            if hashlib.sha256(bundle.read(name)).hexdigest() != sha256(ROOT / name):
                problems.append(f"{name} differs from the project file")
        size = sum(info.file_size for info in bundle.infolist())
    return {"passed": not problems, "problems": problems, "entries": len(names), "required_files_present": REQUIRED,
            "uncompressed_bytes": size, "contents": names}


def clean_run(archive: Path) -> dict:
    """Extract the ZIP into an empty folder and run the final tests on that copy alone."""
    workspace = Path(tempfile.mkdtemp(prefix="prism_clean_"))
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(workspace)
        shipped = {name: sha256(workspace / name) for name in [*FRAMES, "metadata.json", "scene.blend"]}
        shipped_frames = workspace.parent / f"{workspace.name}_shipped_frames"
        shipped_frames.mkdir()
        for name in FRAMES:
            shutil.copy(workspace / name, shipped_frames / Path(name).name)
        steps = final_tests(workspace)
        passed = all(step["passed"] for step in steps) and len(steps) == 5
        regenerated = {name: (workspace / name).is_file() and sha256(workspace / name) == digest
                       for name, digest in shipped.items()}
        # Frames: identical up to GPU rounding (see tests/test_wrapper.py); most are byte-identical.
        differences = {name: image_difference(shipped_frames / Path(name).name, workspace / name)
                       for name in FRAMES if (workspace / name).is_file()}
        frames_match = len(differences) == len(FRAMES) and all(
            count <= SAME_IMAGE_MAX_PIXELS and largest <= SAME_IMAGE_MAX_LEVELS for count, largest in differences.values())
        shutil.rmtree(shipped_frames, ignore_errors=True)
        return {"passed": passed and frames_match and regenerated["metadata.json"] and regenerated["scene.blend"],
                "extracted_to": "an empty temporary folder (deleted afterwards)",
                "steps": steps,
                "regenerated_frames_match_shipped": frames_match,
                "regenerated_frames_byte_identical": sum(regenerated[name] for name in FRAMES),
                "regenerated_frame_differences": {name: {"pixels": c, "max_levels": m} for name, (c, m) in differences.items() if c},
                "regenerated_metadata_identical_to_shipped": regenerated["metadata.json"],
                "scene_blend_unmodified": regenerated["scene.blend"]}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def git_state() -> dict:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True).stdout.strip()
    return {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": git("rev-parse", "HEAD"),
            "uncommitted_changes": [line for line in git("status", "--porcelain").splitlines() if line],
            "remotes": git("remote", "-v").splitlines()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--team-name", default="team_name", help="Name of the ZIP file (default: team_name)")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.team_name):
        raise SystemExit("--team-name may contain only letters, digits, '_', '-' and '.'")
    started = time.time()
    blender = blender_executable()
    version = subprocess.run([str(blender), "--version"], text=True, capture_output=True).stdout.splitlines()[0]
    report: dict = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"platform": platform.platform(), "python": platform.python_version(), "blender": version},
        "git": git_state(),
        "passed": False,
    }
    try:
        print("Final tests in the project (outputs are regenerated):", flush=True)
        report["project_run"] = {"steps": final_tests(ROOT)}
        report["project_run"]["passed"] = all(s["passed"] for s in report["project_run"]["steps"]) and len(report["project_run"]["steps"]) == 5
        if report["project_run"]["passed"]:
            report["metadata_validation"] = {key: value for key, value in json.loads(
                (ROOT / "outputs" / "validation_report.json").read_text(encoding="utf-8")).items() if key != "frames"}
            archive = build_zip(args.team_name)
            report["zip"] = {"path": str(archive), "bytes": archive.stat().st_size, "sha256": sha256(archive)}
            report["zip_integrity"] = check_zip(archive)
            print(f"  {'PASS' if report['zip_integrity']['passed'] else 'FAIL'} zip_integrity ({report['zip_integrity']['entries']} entries)", flush=True)
            if report["zip_integrity"]["passed"]:
                print("Final tests on a clean extract of the ZIP:", flush=True)
                report["clean_extract_run"] = clean_run(archive)
                report["passed"] = report["clean_extract_run"]["passed"]
    finally:
        report["known_limitations"] = LIMITATIONS
        report["seconds"] = round(time.time() - started, 1)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(f"PACKAGE_FAILED see {REPORT}")
    print(f"PACKAGE_OK zip={report['zip']['path']} bytes={report['zip']['bytes']} report={REPORT}")


if __name__ == "__main__":
    main()
