"""Center through-hole check.

The saved disk-center pixel seeds a 4-connected flood through the bright
opening inside the calibrated inner ring.  Bolt holes stay separate islands.
An island that reaches the image frame or the inner-ring boundary is flagged
for review because the closed through-hole wall was not fully photographed.

The recommended compass center may move by at most a tenth of the inner
radius; its integer pixel radius is chosen so the closed disk (circumference
included) contains no measured metal sample.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from image_lab.validation import Invalid, number

from .rim import LUMA

#: Hard limit for moving the compass center, as a fraction of inner radius.
OFFSET_FRACTION = 0.1
#: Score trades one pixel of offset against this many pixels of clearance.
OFFSET_WEIGHT = 0.25
_EPS = 1e-9
_CROSS = ((0, 1, 0), (1, 1, 1), (0, 1, 0))


def seed_pixel(value):
    """Pixel containing a calibrated coordinate; coordinates are non-negative."""
    return int(math.floor(float(value) + 0.5))


def safe_radius(clearance):
    """Largest integer radius with no metal sample at distance <= radius.

    ``clearance`` is the strict Euclidean distance to the nearest measured
    metal sample (or the frame).  The circumference counts as touching, so
    an exact integer clearance only permits the integer below it.
    """
    if not math.isfinite(clearance) or clearance <= 0:
        return 0
    return float(max(0, math.ceil(clearance - _EPS) - 1))


def _round(value, digits=3):
    return round(float(value), digits)


def segment(image, config):
    """Threshold inside the inner ring and 4-connect from the disk center."""
    height, width = image.shape[:2]
    luma = image @ LUMA
    cx, cy = float(config["cx"]), float(config["cy"])
    inner = float(config["inner"])
    cutoff = float(config["cutoff"])
    sx, sy = seed_pixel(cx), seed_pixel(cy)

    yy, xx = np.indices((height, width))
    radius = np.hypot(xx - cx, yy - cy)
    domain = radius <= inner + _EPS
    bright = luma > cutoff
    opening = bright & domain
    metal = ~bright

    seed_inside = 0 <= sx < width and 0 <= sy < height
    seed_opening = bool(seed_inside and opening[sy, sx])

    labels, component_count = ndimage.label(opening, structure=_CROSS)
    if seed_opening:
        component = labels == labels[sy, sx]
    else:
        component = np.zeros((height, width), dtype=bool)

    image_edge = bool(component[0, :].any() or component[-1, :].any()
                      or component[:, 0].any() or component[:, -1].any())
    inner_edge = bool(ndimage.binary_dilation(component, structure=_CROSS)[~domain].any())

    if metal.any():
        distance, nearest = ndimage.distance_transform_edt(~metal, return_indices=True)
    else:
        distance = np.full((height, width), np.inf, dtype=float)
        nearest = None

    ys, xs = np.where(component)
    max_radius = float(radius[component].max()) if len(xs) else 0.0
    reasons = []
    if not seed_opening:
        reasons.append("seed_not_opening")
    if image_edge:
        reasons.append("image_edge")
    if inner_edge:
        reasons.append("inner_edge")

    return {
        "width": width, "height": height, "luma": luma, "cx": cx, "cy": cy,
        "inner": inner, "cutoff": cutoff, "sx": sx, "sy": sy,
        "seed_inside": seed_inside, "seed_opening": seed_opening,
        "domain": domain, "opening": opening,
        "metal": metal, "distance": distance, "nearest": nearest,
        "component": component, "component_count": int(component_count),
        "opening_pixels": int(opening.sum()),
        "component_pixels": int(component.sum()),
        "excluded_components": max(0, int(component_count) - (1 if seed_opening else 0)),
        "excluded_pixels": int(opening.sum() - component.sum()),
        "image_edge": image_edge, "inner_edge": inner_edge,
        "max_radius": max_radius, "reasons": reasons,
        "review": bool(reasons), "closed": seed_opening and not image_edge and not inner_edge,
    }


def _circle(seg, gx, gy, score=None):
    width, height = seg["width"], seg["height"]
    distance = seg["distance"]
    offset = math.hypot(gx - seg["cx"], gy - seg["cy"])
    metal_distance = float(distance[gy, gx]) if np.isfinite(distance[gy, gx]) else None
    frame_distance = min(gx + 0.5, width - 0.5 - gx, gy + 0.5, height - 0.5 - gy)
    if metal_distance is None:
        clearance = frame_distance
    else:
        clearance = min(metal_distance, frame_distance)
    radius = safe_radius(clearance)
    info = {
        "gx": int(gx), "gy": int(gy), "x": int(gx), "y": int(gy),
        "offset": _round(offset), "center_offset_px": _round(offset),
        "max_offset_px": _round(seg["inner"] * OFFSET_FRACTION),
        "metal_distance": None if metal_distance is None else _round(metal_distance),
        "frame_distance": _round(frame_distance),
        "clearance": _round(clearance), "wall_distance": _round(clearance),
        # Strict supremum: a circle must stay just below this radius; the
        # adopted integer ``radius`` is the guaranteed non-touching size.
        "maximum_radius": _round(clearance),
        "maximum_diameter": _round(2 * clearance),
        "radius": radius, "radius_px": int(radius),
        "diameter": 2 * radius, "diameter_px": int(2 * radius),
    }
    if score is not None:
        info["score"] = _round(score, 4)
    return info


def _candidate_grid(seg):
    """All integer centers in the offset budget that lie in the opening."""
    cx, cy = seg["cx"], seg["cy"]
    width, height = seg["width"], seg["height"]
    limit = seg["inner"] * OFFSET_FRACTION
    x0 = max(0, int(math.floor(cx - limit)))
    x1 = min(width - 1, int(math.ceil(cx + limit)))
    y0 = max(0, int(math.floor(cy - limit)))
    y1 = min(height - 1, int(math.ceil(cy + limit)))
    gys, gxs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    offset = np.hypot(gxs - cx, gys - cy)
    keep = (offset <= limit + _EPS) & seg["component"][gys, gxs]
    return gxs[keep], gys[keep], offset[keep]


def recommend(seg):
    """Return the balanced recommendation and the pure largest-circle pick."""
    if not seg["seed_opening"] or not seg["component"].any():
        return None, None
    gxs, gys, offsets = _candidate_grid(seg)
    if len(gxs) == 0:
        return None, None

    width, height = seg["width"], seg["height"]
    frame = np.minimum.reduce([
        gxs + 0.5, width - 0.5 - gxs, gys + 0.5, height - 0.5 - gys,
    ])
    metal_distance = seg["distance"][gys, gxs]
    clearance = np.minimum(metal_distance, frame)
    radii = np.ceil(clearance - _EPS).astype(int) - 1
    radii = np.maximum(radii, 0)
    score = clearance - OFFSET_WEIGHT * offsets

    # Deterministic ordering: best score, then smallest offset, top-left.
    order = np.lexsort((gxs, gys, offsets, -score))
    best = int(order[0])
    recommended = _circle(seg, int(gxs[best]), int(gys[best]), float(score[best]))

    # Pure capacity pick: greatest clearance, tie nearest to the saved center.
    biggest = np.lexsort((gxs, gys, offsets, -clearance))[0]
    largest = _circle(seg, int(gxs[biggest]), int(gys[biggest]), float(score[biggest]))
    largest.pop("score", None)
    return recommended, largest


def wall_points(seg, gx, gy, tolerance=1e-6, cap=36):
    """Actual nearest measured-metal points around a compass center."""
    distance = seg["distance"]
    if seg["metal"].any():
        nearest_distance = float(distance[gy, gx])
    else:
        nearest_distance = math.inf
    if not math.isfinite(nearest_distance):
        return []
    reach = int(math.ceil(nearest_distance)) + 2
    x0 = max(0, gx - reach)
    x1 = min(seg["width"] - 1, gx + reach)
    y0 = max(0, gy - reach)
    y1 = min(seg["height"] - 1, gy + reach)
    sub = seg["metal"][y0:y1 + 1, x0:x1 + 1]
    ys, xs = np.where(sub)
    if not len(xs):
        return []
    px = xs + x0
    py = ys + y0
    gaps = np.hypot(px - gx, py - gy)
    minimum = float(gaps.min())
    chosen = np.flatnonzero(gaps <= minimum + max(tolerance, 1e-6))
    rows = []
    for index in chosen[:cap]:
        x, y = int(px[index]), int(py[index])
        rows.append({
            "x": x, "y": y,
            "distance": _round(gaps[index]),
            "angle": _round(math.degrees(math.atan2(y - gy, x - gx)) % 360, 2),
            "brightness": _round(float(seg["luma"][y, x]), 2),
        })
    rows.sort(key=lambda point: (point["angle"], point["x"], point["y"]))
    return rows


def tightest(seg, compass):
    points = wall_points(seg, compass["gx"], compass["gy"])
    if not points:
        return None, []
    radius = float(compass["radius"])
    for point in points:
        point["margin"] = _round(point["distance"] - radius)
    primary = min(points, key=lambda point: (point["distance"], point["angle"], point["x"]))
    return primary, points


def directional_wall(seg, compass, angle):
    """First measured metal along ``angle`` from the adopted compass center.

    The ray is only verified while it stays inside the calibrated inner ring
    and the image.  Leaving either without meeting metal means no observed
    hole wall and the margin is left empty (None).
    """
    gx, gy = int(compass["gx"]), int(compass["gy"])
    radius = float(compass["radius"])
    theta = math.radians(float(angle))
    dx, dy = math.cos(theta), math.sin(theta)
    cx, cy, inner = seg["cx"], seg["cy"], seg["inner"]
    width, height = seg["width"], seg["height"]
    limit = int(math.hypot(width, height)) + 4

    for ray_radius in range(limit):
        x = int(np.rint(gx + ray_radius * dx))
        y = int(np.rint(gy + ray_radius * dy))
        if not (0 <= x < width and 0 <= y < height):
            return {"angle": _round(angle, 3), "wall": None, "margin": None,
                    "reason": "image_edge"}
        if math.hypot(x - cx, y - cy) > inner + _EPS:
            return {"angle": _round(angle, 3), "wall": None, "margin": None,
                    "reason": "inner_edge"}
        if bool(seg["metal"][y, x]):
            distance = math.hypot(x - gx, y - gy)
            return {
                "angle": _round(angle, 3),
                "wall": {"x": x, "y": y, "ray_radius": ray_radius,
                         "distance": _round(distance),
                         "angle_from_compass": _round(
                             math.degrees(math.atan2(y - gy, x - gx)) % 360, 2),
                         "brightness": _round(float(seg["luma"][y, x]), 2)},
                "distance": _round(distance),
                "margin": _round(distance - radius),
                "ray_margin": _round(ray_radius - radius),
                "reason": None,
            }
    return {"angle": _round(angle, 3), "wall": None, "margin": None, "reason": "range"}


def adopted_marks(image, config, compass):
    """Marks and margins for a persisted adopted compass."""
    seg = segment(image, config)
    return adopted_marks_for(seg, config, compass)


def adopted_marks_for(seg, config, compass):
    clean = validate_stored(compass, seg["width"], seg["height"])
    gx, gy = clean["gx"], clean["gy"]
    offset = math.hypot(gx - seg["cx"], gy - seg["cy"])
    limit = seg["inner"] * OFFSET_FRACTION
    metal_distance = float(seg["distance"][gy, gx]) if np.isfinite(seg["distance"][gy, gx]) else None
    frame_distance = min(gx + 0.5, seg["width"] - 0.5 - gx, gy + 0.5, seg["height"] - 0.5 - gy)
    clearance = frame_distance if metal_distance is None else min(metal_distance, frame_distance)
    primary, points = tightest(seg, clean)
    direction = directional_wall(seg, clean, config["angle"])
    radius = clean["radius"]
    return {
        **clean,
        "offset": _round(offset),
        "max_offset": _round(limit),
        "within_center_limit": offset <= limit + _EPS,
        "current_clearance": _round(clearance),
        "fits_current_metal": radius + _EPS < clearance,
        "tightest": primary,
        "wall_points": points,
        "direction": direction,
        "review": seg["review"],
        "leaks": {"image_edge": seg["image_edge"], "inner_edge": seg["inner_edge"]},
    }


def validate_stored(compass, width=None, height=None):
    if not isinstance(compass, dict):
        raise Invalid("已采用圆规数据无效")
    gx = int(number(compass.get("gx"), "规心 X"))
    gy = int(number(compass.get("gy"), "规心 Y"))
    radius = number(compass.get("radius", 0), "圆规半径", 0)
    if width is not None and not (0 <= gx < width and 0 <= gy < height):
        raise Invalid("已采用规心超出原片范围")
    return {"gx": gx, "gy": gy, "radius": float(radius),
            "diameter": 2 * float(radius)}


def inspect(image, config, adopted=None, seg=None):
    """Full payload for the bore panel / API."""
    seg = seg if seg is not None else segment(image, config)
    recommended, largest = recommend(seg)
    payload = {
        "available": recommended is not None,
        "seed": {"x": seg["sx"], "y": seg["sy"],
                 "brightness": _round(float(seg["luma"][seg["sy"], seg["sx"]]), 2)
                 if seg["seed_inside"] else None,
                 "opening": seg["seed_opening"]},
        "inner_radius": int(seg["inner"]),
        "offset_fraction": OFFSET_FRACTION,
        "max_offset": _round(seg["inner"] * OFFSET_FRACTION),
        "cutoff": int(seg["cutoff"]),
        "opening_pixels": seg["opening_pixels"],
        "component_pixels": seg["component_pixels"],
        "excluded_components": seg["excluded_components"],
        "excluded_pixels": seg["excluded_pixels"],
        "max_component_radius": _round(seg["max_radius"], 2),
        "touches_image_edge": seg["image_edge"],
        "touches_inner_edge": seg["inner_edge"],
        "leaks": {"image_edge": seg["image_edge"], "inner_edge": seg["inner_edge"]},
        "review": seg["review"],
        "closed": seg["closed"],
        "reasons": seg["reasons"],
        "recommended": recommended,
        "largest": largest,
        "adopted": None,
    }
    if recommended is not None:
        primary, points = tightest(seg, recommended)
        payload["tightest"] = primary
        payload["wall_points"] = points
        seed_circle = {"gx": seg["sx"], "gy": seg["sy"],
                       "radius": safe_radius(float(seg["distance"][seg["sy"], seg["sx"]]))}
        center_primary, _ = tightest(seg, seed_circle)
        payload["center_tightest"] = center_primary
        payload["recommended_direction"] = directional_wall(seg, recommended, config["angle"])
    else:
        payload["tightest"] = None
        payload["wall_points"] = []
        payload["center_tightest"] = None
        payload["recommended_direction"] = None
    if adopted:
        payload["adopted"] = adopted_marks_for(seg, config, adopted)
    return payload


def resolve_adoption(image, config, body=None):
    """Validate an adoption request against the measured metal.

    An empty body adopts the balanced recommendation.  Explicit centers must
    respect the tenth-of-inner-radius budget and lie in the connected opening;
    an explicit radius that would cover measured metal is rejected.
    """
    seg = segment(image, config)
    recommended, _ = recommend(seg)
    if recommended is None:
        raise Invalid("盘心像素不是连通亮开口，无法采用圆规，请先复核盘心/亮度上限")

    body = body if isinstance(body, dict) else {}
    has_center = any(key in body for key in ("gx", "gy", "x", "y", "compass_x", "compass_y"))
    if not has_center:
        chosen = dict(recommended)
        source = "recommended"
    else:
        raw_x = body.get("gx", body.get("x", body.get("compass_x")))
        raw_y = body.get("gy", body.get("y", body.get("compass_y")))
        gx = seed_pixel(number(raw_x, "规心 X", 0, seg["width"] - 1))
        gy = seed_pixel(number(raw_y, "规心 Y", 0, seg["height"] - 1))
        limit = seg["inner"] * OFFSET_FRACTION
        offset = math.hypot(gx - seg["cx"], gy - seg["cy"])
        if offset > limit + _EPS:
            raise Invalid(f"规心偏离当前盘心 {offset:.1f} px，超过内环半径十分之一 {limit:.1f} px")
        if not seg["component"][gy, gx]:
            raise Invalid("规心必须位于连回盘心的开口像素内")
        chosen = _circle(seg, gx, gy)
        source = "custom"

    if body.get("radius") is not None:
        requested = number(body["radius"], "圆规半径", 0)
        # The circumference counts: equality already touches the metal.
        if requested + _EPS >= chosen["clearance"]:
            raise Invalid("该半径的圆周或圆内会碰到实测金属")
        chosen["radius"] = float(requested)
        chosen["diameter"] = 2 * float(requested)

    compass = {
        "gx": int(chosen["gx"]), "gy": int(chosen["gy"]),
        "radius": float(chosen["radius"]), "diameter": float(chosen["diameter"]),
        "source": source,
        "offset": chosen["offset"], "clearance": chosen["clearance"],
    }
    return compass
