"""End-to-end test of the ground-truth metadata (Stage 5B).

    python3 tests/test_metadata.py

Renders the ten frames afresh in the real Blender scene, generates the official
``metadata.json``, validates it against the rendered pixels, and then confirms
that the validator rejects each kind of wrong metadata.
"""
from __future__ import annotations

from pathlib import Path
import copy
import json
import math
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metadata.metadata_generator import REQUIRED_KEYS, build_metadata, generate, official_record
from metadata.validator import (METADATA_PATH, PROVENANCE_PATH, RENDERS_DIR, REPORT_PATH,
                                MetadataValidationError, project, validate)


def expect_rejection(label: str, fragment: str, records: object, directory: Path, *, raw: str | None = None,
                     renders_dir: Path = RENDERS_DIR) -> None:
    """The validator must refuse ``records`` and say why."""
    path = directory / "tampered.json"
    path.write_text(raw if raw is not None else json.dumps(records), encoding="utf-8")
    try:
        validate(path, renders_dir=renders_dir, report_path=directory / "report.json")
    except MetadataValidationError as error:
        assert fragment.lower() in str(error).lower(), f"{label}: rejected for another reason:\n{error}"
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        assert report["valid"] is False and report["errors"], f"{label}: the failure report is not marked invalid"
        print(f"REJECTED {label}: {error.errors[0]}")
    else:
        raise AssertionError(f"{label}: wrong metadata was accepted")


def main() -> None:
    path = generate()  # fresh Blender renders and measurements
    assert path == METADATA_PATH
    report = validate(path)
    records = json.loads(path.read_text(encoding="utf-8"))
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))["frames"]

    # The files asked for exist and agree with each other.
    saved = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert saved == report and report["valid"] is True and report["errors"] == []
    assert report["records"] == 10 and len(report["frames"]) == 10
    assert report["summary"]["pupils_located_in_pixels"] == 20, "Not every pupil was found in the rendered pixels"
    assert report["summary"]["max_rendered_pixel_error_px"] <= 1.5
    assert report["summary"]["max_reprojection_error_px"] <= 0.01
    assert report["summary"]["max_gaze_error_to_target_degrees"] <= 0.01
    assert report["summary"]["camera_fixed"] is True
    assert abs(report["camera"]["camera_distance_m"] - 0.400) < 1e-5

    # Schema, numbering, formula, and strictly standard JSON (no NaN / Infinity tokens).
    text = path.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    for k, record in enumerate(records):
        theta = 2.0 * math.pi * k / 10.0
        assert tuple(record) == REQUIRED_KEYS, f"frame {k}: keys are {list(record)}"
        assert record["frame"] == k and record["theta"] == theta
        assert record["input"] == {"h": math.sin(theta), "v": math.cos(theta)}
        assert record == official_record(provenance[k]), f"frame {k}: record differs from the Blender measurement"
    assert records == build_metadata(provenance)

    # The values are measurements, not constants: they differ per frame and per eye,
    # and the pupil centre is not the eyeball centre.
    for key in ("eye_rotation_L", "eye_rotation_R", "pupil_center_2D_L", "pupil_center_2D_R"):
        assert len({tuple(record[key]) for record in records}) == 10, f"{key} does not change with the gaze"
    for record, measured in zip(records, provenance):
        assert record["eye_rotation_L"] != record["eye_rotation_R"], "Converging eyes cannot share one rotation"
        for side in ("L", "R"):
            eyeball = project(record["camera_matrix"], measured["eye_center_world_m"][side])
            pupil = record[f"pupil_center_2D_{side}"]
            assert math.hypot(pupil[0] - eyeball[0], pupil[1] - eyeball[1]) > 5.0, "A pupil centre equals its eyeball centre"
    summary = report["summary"]
    print(f"METADATA_OK records=10 max_gaze_error_deg={summary['max_gaze_error_to_target_degrees']:.2e} "
          f"max_reprojection_px={summary['max_reprojection_error_px']:.2e} "
          f"rendered_pixel_error_px max={summary['max_rendered_pixel_error_px']:.3f} "
          f"mean={summary['mean_rendered_pixel_error_px']:.3f}")

    # The generator refuses non-finite or missing measurements.
    for label, change in (("NaN rotation", lambda m: m["world_eye_rotations_euler_xyz_degrees"]["L"].__setitem__(0, float("nan"))),
                          ("infinite pupil", lambda m: m["pupil_center_2D"]["R"].__setitem__(1, float("inf"))),
                          ("missing camera matrix", lambda m: m.pop("camera_matrix")),
                          ("short rotation", lambda m: m["world_eye_rotations_euler_xyz_degrees"]["R"].pop())):
        broken = copy.deepcopy(provenance)
        change(broken[4])
        try:
            build_metadata(broken)
        except ValueError as error:
            print(f"GENERATOR_REFUSED {label}: {error}")
        else:
            raise AssertionError(f"The generator accepted a {label}")

    # The validator rejects every kind of wrong metadata, on copies; the real files are untouched.
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)

        def tampered(change) -> list:
            result = copy.deepcopy(records)
            change(result)
            return result

        def eyeball_instead_of_pupil(result: list) -> None:
            for record, measured in zip(result, provenance):
                for side in ("L", "R"):
                    record[f"pupil_center_2D_{side}"] = project(record["camera_matrix"], measured["eye_center_world_m"][side])

        def swap_eyes(result: list) -> None:
            for record in result:
                record["pupil_center_2D_L"], record["pupil_center_2D_R"] = record["pupil_center_2D_R"], record["pupil_center_2D_L"]

        def scale_camera(result: list) -> None:
            for record in result:
                record["camera_matrix"][0][0] *= 1.01

        cases = (
            ("nine records", "expected 10 records", tampered(lambda r: r.pop())),
            ("missing field", "missing required field", tampered(lambda r: r[2].pop("pupil_center_2D_R"))),
            ("unexpected field", "unexpected field", tampered(lambda r: r[2].__setitem__("note", 1))),
            ("frame numbering", "frame is", tampered(lambda r: r[6].__setitem__("frame", 7))),
            ("reordered records", "frame is", tampered(lambda r: r.reverse())),
            ("wrong theta", "theta is", tampered(lambda r: r[3].__setitem__("theta", 1.8849))),
            ("rounded input", "input is", tampered(lambda r: r[3].__setitem__("input", {"h": 0.951, "v": -0.309}))),
            ("string value", "not a finite number", tampered(lambda r: r[1].__setitem__("theta", "0.628"))),
            ("rotation of two angles", "eye_rotation_l must be 3", tampered(lambda r: r[1]["eye_rotation_L"].pop())),
            ("rotation off by one degree", "fixation target", tampered(lambda r: r[5]["eye_rotation_R"].__setitem__(2, r[5]["eye_rotation_R"][2] + 1.0))),
            ("rotations of another frame", "fixation target", tampered(lambda r: r[2].__setitem__("eye_rotation_L", r[7]["eye_rotation_L"]))),
            ("zero rotations", "fixation target", tampered(lambda r: [x.update(eye_rotation_L=[0.0, 0.0, 0.0], eye_rotation_R=[0.0, 0.0, 0.0]) for x in r])),
            ("pupil shifted three pixels", "projected 3d pupil centre", tampered(lambda r: r[4]["pupil_center_2D_L"].__setitem__(0, r[4]["pupil_center_2D_L"][0] + 3.0))),
            ("eyeball centres instead of pupils", "projected 3d pupil centre", tampered(eyeball_instead_of_pupil)),
            ("pupil outside image", "outside the image", tampered(lambda r: r[4].__setitem__("pupil_center_2D_R", [1500.0, 512.0]))),
            ("left and right swapped", "not left of", tampered(swap_eyes)),
            ("camera moved in one frame", "camera must be fixed", tampered(lambda r: r[8]["camera_matrix"][2].__setitem__(3, 0.6))),
            ("camera matrix altered in every frame", "differs from k [r | t]", tampered(scale_camera)),
            ("camera matrix 3 x 3", "camera_matrix must be 3 x 4", tampered(lambda r: [row.pop() for row in r[0]["camera_matrix"]])),
        )
        for label, fragment, wrong in cases:
            expect_rejection(label, fragment, wrong, directory)
        for token in ("NaN", "Infinity", "-Infinity"):
            raw = json.dumps(records).replace(json.dumps(records[1]["eye_rotation_L"][0]), token, 1)
            assert token in raw
            expect_rejection(f"{token} value", "non-numeric json value", None, directory, raw=raw)

        # A record must belong to its own image: swap two frames' PNGs and remove one.
        swapped = directory / "renders"
        shutil.copytree(RENDERS_DIR, swapped, ignore=lambda _, names: [n for n in names if not n.startswith("frame_")])
        shutil.copy(RENDERS_DIR / "frame_02.png", swapped / "frame_07.png")
        expect_rejection("another frame's image", "sha-256 differs", records, directory, renders_dir=swapped)
        (swapped / "frame_07.png").unlink()
        expect_rejection("missing image", "is missing", records, directory, renders_dir=swapped)
        (swapped / "frame_07.png").write_bytes(b"not an image")
        expect_rejection("corrupt image", "is invalid", records, directory, renders_dir=swapped)

    assert json.loads(REPORT_PATH.read_text(encoding="utf-8")) == report, "A rejection test overwrote the real report"
    assert json.loads(METADATA_PATH.read_text(encoding="utf-8")) == records
    print("METADATA_TEST_OK records=10 actual_pixels=true numeric_json=true generator_refusals=4 validator_rejections=25")


if __name__ == "__main__":
    main()
