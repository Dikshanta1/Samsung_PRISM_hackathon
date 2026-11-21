"""Standard-library pupil measurements on decoded PNG rows (no numpy, no bpy).

Two independent pixel checks of the 2D pupil ground truth:

* ``mask_centroids`` -- the exact check. ``blender/pupil_mask.py`` renders the
  same pose through the same camera with only the textured pupils, white on
  black. The intensity-weighted centroid of each disc is where the renderer
  actually drew the pupil, to a small fraction of a pixel.
* ``pupil_contrast`` -- a sanity check on the photoreal RGB frame itself: the
  reported centre must sit on a dark pupil, clearly darker than the iris just
  below it. (The iris above the pupil is shaded by the upper lid, so it is not
  used.) A corneal catchlight can lie across the pupil in some gaze
  directions, as on a real eye, so the core is measured by its darkest fifth
  of pixels rather than its median.

``rows`` is anything indexable by row number that returns that row's RGB bytes
(a list or a dict of decoded rows).
"""
from __future__ import annotations

from statistics import median

IMAGE_SIZE_PX = 1024
MASK_BAND_ROWS = (412, 612)  # every allowed gaze keeps both pupils inside these rows
MASK_FLOOR = 4  # 8-bit levels at or below this are background, not pupil coverage
PUPIL_CORE_RADIUS_PX = 5.0
PUPIL_CORE_FRACTION = 0.2  # the darkest fifth of the core disc
IRIS_BELOW_RADII_PX = (15.0, 22.0)  # annulus in the lower iris, outside the pupil (radius about 12 px)
PUPIL_CORE_MAX_LEVEL = 64  # 0.25: the pupil core is dark
PUPIL_CONTRAST_MIN_LEVELS = 25  # and at least 0.1 darker than the iris below it


def mask_centroids(rows, band: tuple[int, int] = MASK_BAND_ROWS) -> dict[str, list[float]]:
    """Centroid ``[u, v]`` (pixel centres at +0.5) of each pupil disc in a mask image.

    ``L`` is the subject's left eye, on the right half of the image. Raises
    ``ValueError`` if a disc is missing.
    """
    sums = {"L": [0.0, 0.0, 0.0], "R": [0.0, 0.0, 0.0]}
    half = IMAGE_SIZE_PX // 2
    for row in range(band[0], band[1]):
        line = rows[row]
        for column in range(IMAGE_SIZE_PX):
            level = line[3 * column] + line[3 * column + 1] + line[3 * column + 2]
            if level <= 3 * MASK_FLOOR:
                continue
            total = sums["L" if column >= half else "R"]
            total[0] += level * (column + 0.5)
            total[1] += level * (row + 0.5)
            total[2] += level
    result = {}
    for side, (su, sv, weight) in sums.items():
        if weight < 3 * 255 * 20:
            raise ValueError(f"pupil {side} is missing from the mask")
        result[side] = [su / weight, sv / weight]
    return result


def pupil_contrast(rows, centre: list[float] | tuple[float, float]) -> tuple[float, float]:
    """``(core, iris_below)``: brightest-channel levels of the pupil core (darkest fifth) and the iris below it (median)."""
    cu, cv = centre
    inner, outer = IRIS_BELOW_RADII_PX
    core, below = [], []
    for row in range(int(cv - outer) - 1, int(cv + outer) + 2):
        line = rows[row]
        dv = row + 0.5 - cv
        for column in range(int(cu - outer) - 1, int(cu + outer) + 2):
            du = column + 0.5 - cu
            distance_sq = du * du + dv * dv
            level = max(line[3 * column:3 * column + 3])
            if distance_sq <= PUPIL_CORE_RADIUS_PX ** 2:
                core.append(level)
            elif inner ** 2 <= distance_sq <= outer ** 2 and dv > inner / 2:
                below.append(level)
    core.sort()
    return float(core[int(PUPIL_CORE_FRACTION * (len(core) - 1))]), float(median(below))


def pupil_contrast_problem(rows, centre) -> str | None:
    """``None`` if ``centre`` is on the dark pupil of the RGB frame, else the reason it is not."""
    core, below = pupil_contrast(rows, centre)
    if core > PUPIL_CORE_MAX_LEVEL:
        return f"is not on a dark pupil (core level {core:.0f}/255)"
    if below - core < PUPIL_CONTRAST_MIN_LEVELS:
        return f"is not darker than the iris below it (core {core:.0f}, iris {below:.0f})"
    return None
