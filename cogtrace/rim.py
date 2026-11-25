"""Read original dark-material outlines in a user-calibrated radial band."""

from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid, integer, number


LUMA = np.array([0.2126, 0.7152, 0.0722])
MAX_IMAGE_BYTES = 18 * 1024 * 1024


def png(image):
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def decode(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise Invalid("单张原片不得超过18 MiB")
    try:
        with Image.open(BytesIO(data)) as photo:
            if photo.format not in {"PNG", "JPEG", "TIFF", "BMP", "WEBP"} or getattr(photo, "n_frames", 1) != 1:
                raise Invalid("请选择单帧 PNG、JPEG、TIFF、BMP 或 WebP")
            if min(photo.size) < 32 or max(photo.size) > 2600 or math.prod(photo.size) > 4_000_000:
                raise Invalid("原片边长须在32–2600 px内，总像素不超过400万")
            normalized = ImageOps.exif_transpose(photo).convert("RGB")
            return normalized.size, png(normalized)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise Invalid("原片无法解码") from error


def pixels(path):
    with Image.open(path) as photo:
        return np.asarray(photo.convert("RGB"))


def settings(value, size):
    width, height = size
    inner = integer(value.get("inner"), "内环半径", 2, max(size) - 3)
    return {
        "cx": number(value.get("cx"), "盘心 X", 0, width - 1),
        "cy": number(value.get("cy"), "盘心 Y", 0, height - 1),
        "inner": inner,
        "outer": integer(value.get("outer"), "外环半径", inner + 2, max(size)),
        "cutoff": integer(value.get("cutoff"), "金属亮度上限", 1, 254),
        "angle": number(value.get("angle"), "核查角度", 0, 360) % 360,
        "teeth": integer(value.get("teeth"), "手填齿数", 6, 120),
    }


def defaults(size):
    width, height = size
    return settings({"cx": width // 2, "cy": height // 2, "inner": max(2, int(min(size) * .27)),
                     "outer": int(min(size) * .48), "cutoff": 140, "angle": 0, "teeth": 24}, size)


def comparison_state(value, config):
    """Validate the small, persistable adopted-comparison parameters."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise Invalid("双齿对照设置必须是对象")
    reference = wrap_angle(number(value.get("reference_angle", config["angle"]), "完好齿选角"))
    suspect = wrap_angle(number(value.get("suspect_angle", config["angle"]), "待查齿选角"))
    limit = tooth_pitch(config) / 4.0
    offset_value = value.get("offset", value.get("adopted_offset_deg"))
    offset = None if offset_value is None else number(offset_value, "采用角偏", -limit, limit)
    point_value = value.get("comparison_angle", value.get("relative_angle", 0.0))
    point_angle = number(point_value, "对照角")
    half = tooth_pitch(config) / 2.0
    if abs(point_angle) > half + 1e-7:
        raise Invalid(f"对照角必须在 ±{half:.3f}° 内")
    return {"reference_angle": reference, "suspect_angle": suspect,
            "offset": offset, "comparison_angle": point_angle}


def polar(x, y, config):
    dx, dy = x - config["cx"], y - config["cy"]
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx)) % 360


def point(image, x, y, config):
    r, angle = polar(x, y, config)
    rgb = image[y, x]
    level = float(rgb @ LUMA)
    return {"x": x, "y": y, "radius": r, "angle": angle, "rgb": [int(value) for value in rgb],
            "brightness": level, "metal": bool(level <= config["cutoff"])}


def ray(image, angle, config):
    radians = math.radians(angle)
    radii = np.arange(config["inner"], config["outer"] + 1)
    xs = np.rint(config["cx"] + radii * math.cos(radians)).astype(int)
    ys = np.rint(config["cy"] + radii * math.sin(radians)).astype(int)
    height, width = image.shape[:2]
    visible = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    x, y, r = xs[visible], ys[visible], radii[visible]
    levels = image[y, x] @ LUMA
    metal = levels <= config["cutoff"]
    actual_angle = np.degrees(np.arctan2(y - config["cy"], x - config["cx"])) % 360
    return {"angle": angle, "r": r, "x": x, "y": y, "brightness": levels,
            "metal": metal, "actual_angle": actual_angle}


def edge(trace):
    candidates = np.flatnonzero(trace["metal"])
    if not len(candidates):
        return None
    index = candidates[-1]
    actual_angle = None
    if "actual_angle" in trace:
        actual_angle = float(trace["actual_angle"][index])
    return {"radius": int(trace["r"][index]), "x": int(trace["x"][index]),
            "y": int(trace["y"][index]), "actual_angle": actual_angle,
            "source_angle": actual_angle}


def report(image, config):
    active = ray(image, config["angle"], config)
    profile = []
    for r, x, y, brightness, metal in zip(active["r"], active["x"], active["y"], active["brightness"], active["metal"]):
        profile.append({"r": int(r), "x": int(x), "y": int(y), "brightness": float(brightness), "metal": bool(metal)})
    sweep = []
    for angle in range(360):
        actual = edge(ray(image, angle, config))
        sweep.append({"angle": angle, "edge": actual})
    step = 360 / config["teeth"]
    return {"reading": edge(active), "angle": config["angle"], "manual_pitch_deg": step,
            "profile": profile, "sweep": sweep}


def wrap_angle(value):
    """Normalize a source-photo direction to the app's 0–360° convention."""
    return float(value) % 360.0


def signed_angle_delta(angle, center):
    return (float(angle) - float(center) + 180.0) % 360.0 - 180.0


def tooth_pitch(config):
    return 360.0 / config["teeth"]


def sector_relative_angles(config):
    """Integer-degree check angles inside selected_angle ± half a manual pitch."""
    half = tooth_pitch(config) / 2.0
    first = math.ceil(-half - 1e-9)
    last = math.floor(half + 1e-9)
    return [float(value) for value in range(first, last + 1)]


def edge_at(image, angle, config, cache=None):
    requested = wrap_angle(angle)
    key = round(requested, 9)
    if cache is not None and key in cache:
        return cache[key]
    found = edge(ray(image, requested, config))
    if found is not None:
        actual = found.get("actual_angle")
        if actual is None:
            _, actual = polar(found["x"], found["y"], config)
        found = {"requested_angle": requested, "angle": requested,
                 "actual_angle": float(actual), "source_angle": float(actual),
                 "actual_angle_deg": float(actual), "source_angle_deg": float(actual),
                 "radius": found["radius"], "x": found["x"], "y": found["y"],
                 "source_x": found["x"], "source_y": found["y"],
                 "pixel": [found["x"], found["y"]],
                 "source_pixel": [found["x"], found["y"]]}
    if cache is not None:
        cache[key] = found
    return found


def comparison_side(relative_angle):
    if relative_angle < -1e-9:
        return "left"
    if relative_angle > 1e-9:
        return "right"
    return "center"


def validate_comparison_alignment(config, offset):
    limit = tooth_pitch(config) / 4.0
    value = number(offset, "采用角偏", -limit, limit)
    if abs(value) > limit + 1e-7:
        raise Invalid(f"角偏不得超过四分之一齿距（±{limit:.3f}°）")
    return value, limit


def comparison_pair(image, config, reference_angle, suspect_angle, relative_angle,
                    offset=0.0, cache=None):
    pitch = tooth_pitch(config)
    half = pitch / 2.0
    offset, limit = validate_comparison_alignment(config, offset)
    relative = float(relative_angle)
    if not math.isfinite(relative):
        raise Invalid("对照角必须有限")
    if abs(relative) > half + 1e-7:
        raise Invalid(f"对照角必须在选角左右半个齿距内（±{half:.3f}°）")

    reference = edge_at(image, reference_angle + relative, config, cache)
    suspect = edge_at(image, suspect_angle + relative + offset, config, cache)
    complete = reference is not None and suspect is not None
    difference = int(reference["radius"] - suspect["radius"]) if complete else None
    positive = bool(complete and difference > 0)
    return {
        "relative_angle": relative,
        "comparison_angle": relative,
        "angle": relative,
        "side": comparison_side(relative),
        "reference": reference,
        "healthy": reference,
        "reference_edge": reference,
        "reference_reading": reference,
        "reference_point": reference,
        "suspect": suspect,
        "candidate": suspect,
        "target": suspect,
        "suspect_edge": suspect,
        "suspect_reading": suspect,
        "suspect_point": suspect,
        "complete": complete,
        "has_both_readings": complete,
        "difference_px": difference,
        "signed_difference_px": difference,
        # A missing source reading stays null; it is never converted into material loss.
        "loss_px": max(0, difference) if complete else None,
        "radial_loss_px": difference if positive else (0 if complete else None),
        "positive_difference": positive,
        "material_loss": positive,
        "missing_reading": not complete,
    }


def _side_summary(pairs, side=None):
    if side is not None:
        scoped = [pair for pair in pairs if pair["side"] == side]
    else:
        scoped = list(pairs)
    complete = [pair for pair in scoped if pair["complete"]]
    if not complete:
        return {"side": side or "all", "check_angles": len(scoped), "complete_pairs": 0,
                "maximum_difference_px": None, "radial_loss_px": None,
                "material_loss": None, "loss_angle": None, "pair": None}
    worst = max(complete, key=lambda pair: pair["difference_px"])
    difference = int(worst["difference_px"])
    return {"side": side or "all", "check_angles": len(scoped),
            "complete_pairs": len(complete), "maximum_difference_px": difference,
            "radial_loss_px": max(0, difference), "material_loss": difference > 0,
            "loss_angle": worst["relative_angle"], "loss_side": worst["side"], "pair": worst}


def _alignment_score(image, config, reference_angle, suspect_angle, offset, angles, cache):
    pairs = [comparison_pair(image, config, reference_angle, suspect_angle, angle, offset, cache)
             for angle in angles]
    left = [abs(pair["difference_px"]) for pair in pairs
            if pair["complete"] and pair["side"] == "left"]
    right = [abs(pair["difference_px"]) for pair in pairs
             if pair["complete"] and pair["side"] == "right"]
    flank_costs = []
    if left:
        flank_costs.append(float(np.median(left)))
    if right:
        flank_costs.append(float(np.median(right)))
    if flank_costs:
        edge_cost = sum(flank_costs) / len(flank_costs)
        basis = "left_right_median_abs_radius_difference"
    else:
        all_differences = [abs(pair["difference_px"]) for pair in pairs if pair["complete"]]
        if not all_differences:
            return {"offset_deg": float(offset), "edge_cost_px": None,
                    "direction_penalty_px": None, "score": None,
                    "complete_pairs": 0, "cost_basis": "no_complete_readings"}
        edge_cost = float(np.median(all_differences))
        basis = "all_median_abs_radius_difference"
    limit = tooth_pitch(config) / 4.0
    # At the permitted quarter-pitch boundary the manual-direction prior costs <1 px.
    direction_penalty = 0.75 * abs(offset) / limit if limit else 0.0
    return {"offset_deg": round(float(offset), 6),
            "edge_cost_px": round(edge_cost, 6),
            "direction_penalty_px": round(direction_penalty, 6),
            "score": round(edge_cost + direction_penalty, 6),
            "complete_pairs": sum(pair["complete"] for pair in pairs),
            "cost_basis": basis}


def align_teeth(image, config, reference_angle, suspect_angle, cache=None):
    pitch = tooth_pitch(config)
    limit = pitch / 4.0
    angles = sector_relative_angles(config)
    step = 0.1
    count = int(math.floor(limit / step + 1e-9))
    offsets = {round(index * step, 4) for index in range(-count, count + 1)}
    offsets.add(round(-limit, 6))
    offsets.add(round(limit, 6))
    candidates = [_alignment_score(image, config, reference_angle, suspect_angle, offset, angles, cache)
                  for offset in sorted(offsets)]
    usable = [candidate for candidate in candidates if candidate["score"] is not None]
    if not usable:
        best_offset = 0.0
        warning = "两个扇段没有足够的共同实拍边读数，角偏仅保留手选方向 0°。"
    else:
        # Readings are integer source pixels.  Within one pixel of the best
        # robust edge match, preserve the user's selected direction rather
        # than chasing raster quantization with a larger angular change.
        best_edge_cost = min(candidate["edge_cost_px"] for candidate in usable)
        close_enough = [candidate for candidate in usable
                        if candidate["edge_cost_px"] <= best_edge_cost + 1e-6]
        chosen = min(close_enough, key=lambda item: (abs(item["offset_deg"]), item["offset_deg"]))
        best_offset = float(chosen["offset_deg"])
        weighted_best = min(usable, key=lambda item: (item["score"], abs(item["offset_deg"]),
                                                       item["offset_deg"]))
        for candidate in candidates:
            candidate["adopted"] = candidate["offset_deg"] == best_offset
            candidate["weighted_best"] = candidate["offset_deg"] == weighted_best["offset_deg"]
        warning = None
    return best_offset, candidates, warning


def compare_teeth(image, config, reference_angle=None, suspect_angle=None,
                  offset=None, point_angle=None, **aliases):
    """Compare same-image tooth sectors without resizing radii or the source image."""
    if reference_angle is None:
        for key in ("healthy_angle", "intact_angle", "good_angle", "ref_angle", "healthy"):
            if aliases.get(key) is not None:
                reference_angle = aliases[key]
                break
    if suspect_angle is None:
        for key in ("target_angle", "candidate_angle", "damaged_angle", "worn_angle",
                    "bad_angle", "checked_angle", "suspect"):
            if aliases.get(key) is not None:
                suspect_angle = aliases[key]
                break
    if point_angle is None:
        for key in ("comparison_angle", "relative_angle", "check_angle", "angle"):
            if aliases.get(key) is not None:
                point_angle = aliases[key]
                break
    if offset is None:
        for key in ("angle_offset", "adopted_offset_deg", "alignment_offset", "shift"):
            if aliases.get(key) is not None:
                offset = aliases[key]
                break
    selected = float(config["angle"])
    reference = wrap_angle(number(reference_angle if reference_angle is not None else selected,
                                 "完好齿选角"))
    suspect = wrap_angle(number(suspect_angle if suspect_angle is not None else selected,
                                "待查齿选角"))
    pitch = tooth_pitch(config)
    half = pitch / 2.0
    limit = pitch / 4.0
    cache = {}
    suggested, candidates, alignment_warning = align_teeth(
        image, config, reference, suspect, cache)

    offset_source = "auto_alignment"
    if offset is None:
        adopted = suggested
    else:
        adopted, _ = validate_comparison_alignment(config, offset)
        offset_source = "manual"

    angles = sector_relative_angles(config)
    rows = [comparison_pair(image, config, reference, suspect, angle, adopted, cache)
            for angle in angles]
    all_summary = _side_summary(rows)
    left_summary = _side_summary(rows, "left")
    right_summary = _side_summary(rows, "right")
    center_summary = _side_summary(rows, "center")

    flank_summaries = [left_summary, right_summary]
    positive_flanks = [item for item in flank_summaries if item["material_loss"]]
    if positive_flanks:
        worst_flank = max(positive_flanks,
                          key=lambda item: (item["radial_loss_px"], item["complete_pairs"]))["side"]
    else:
        ranked_flanks = [item for item in flank_summaries
                         if item["maximum_difference_px"] is not None]
        worst_flank = max(ranked_flanks, key=lambda item: item["maximum_difference_px"])["side"] \
            if ranked_flanks else None

    if point_angle is None:
        point_angle = all_summary["loss_angle"] if all_summary["material_loss"] else 0.0
    point = comparison_pair(image, config, reference, suspect, point_angle, adopted, cache)

    difference = all_summary["maximum_difference_px"]
    result = {
        "reference_selected_angle": reference,
        "suspect_selected_angle": suspect,
        # Common aliases for route/UI consumers.
        "reference_angle": reference,
        "healthy_angle": reference,
        "suspect_angle": suspect,
        "candidate_angle": suspect,
        "target_angle": suspect,
        "manual_pitch_deg": pitch,
        "pitch_deg": pitch,
        "half_pitch_deg": half,
        "sector_half_width_deg": half,
        "max_adjustment_deg": limit,
        "quarter_pitch_deg": limit,
        "offset_deg": adopted,
        "offset": adopted,
        "adopted_offset_deg": adopted,
        "adopted_offset": adopted,
        "angle_offset_deg": adopted,
        "angle_offset": adopted,
        "alignment_offset_deg": adopted,
        "alignment_offset": adopted,
        "suggested_offset_deg": suggested,
        "offset_source": offset_source,
        "scale_locked": True,
        "radius_scale": 1.0,
        "image_resize": "none",
        "radius_scaling": "none",
        "sector_angles": angles,
        "relative_angles": angles,
        "rows": rows,
        "candidates": candidates,
        "alignment": {"offset_deg": adopted, "suggested_offset_deg": suggested,
                      "candidates": candidates, "warning": alignment_warning,
                      "rule": "minimize robust left/right radial mismatch; equal matches choose the smallest manual-direction change"},
        "summary": {"all": all_summary, "left": left_summary, "right": right_summary,
                    "center": center_summary, "worst_flank": worst_flank},
        "left": left_summary,
        "right": right_summary,
        "center": center_summary,
        "worst_side": worst_flank,
        "worst_flank": worst_flank,
        "worst_region": all_summary.get("loss_side"),
        "worst_location": all_summary.get("loss_side"),
        "radial_loss_px": all_summary["radial_loss_px"],
        "radial_loss_pixels": all_summary["radial_loss_px"],
        "loss_px": all_summary["radial_loss_px"],
        "missing_radial_pixels": all_summary["radial_loss_px"],
        "maximum_difference_px": difference,
        "signed_difference_px": difference,
        "material_loss": all_summary["material_loss"] is True and difference > 0,
        "positive_difference": difference is not None and difference > 0,
        "point": point,
        "comparison_point": point,
        # Flatten the selected checkpoint for clients that read the JSON top level.
        "comparison_angle": point["relative_angle"],
        "check_angle": point["relative_angle"],
        "difference_px": point["difference_px"],
        "point_difference_px": point["difference_px"],
        "point_loss_px": point["loss_px"],
        "reference_reading": point["reference"],
        "suspect_reading": point["suspect"],
        "reference_source_angle": point["reference"]["actual_angle"] if point["reference"] else None,
        "suspect_source_angle": point["suspect"]["actual_angle"] if point["suspect"] else None,
        "reference_pixel": [point["reference"]["x"], point["reference"]["y"]] if point["reference"] else None,
        "suspect_pixel": [point["suspect"]["x"], point["suspect"]["y"]] if point["suspect"] else None,
        "warning": alignment_warning,
    }
    return result


def practice():
    w, h = 744, 474
    cfg = settings({"cx": 372, "cy": 237, "inner": 142, "outer": 185,
                    "cutoff": 143, "angle": 0, "teeth": 24}, (w, h))
    yy, xx = np.indices((h, w))
    dx, dy = xx - cfg["cx"], yy - cfg["cy"]
    radius = np.hypot(dx, dy)
    az = np.degrees(np.arctan2(dy, dx)) % 360
    center_sep = np.abs((az + 7.5) % 15 - 7.5)
    crest = np.clip((6.4 - center_sep) / 3.5, 0, 1)
    damage = 6 * np.exp(-((az - 45) / 1.7) ** 2) + 17 * np.exp(-((az - 240) / 3.5) ** 2)
    rim_radius = 150 + 18 * crest - damage
    bolt = np.zeros_like(radius, dtype=bool)
    for a in np.linspace(0, 2 * np.pi, 6, endpoint=False):
        bolt |= np.hypot(dx - 90 * math.cos(a), dy - 90 * math.sin(a)) < 15
    inside = (radius <= rim_radius) & (radius >= 56) & ~bolt
    base = 221 - 14 * xx / w + 9 * np.cos(yy / 172) + 1.2 * np.sin(xx * .73 + yy * .94)
    steel = (86 + 8 * np.cos(az * np.pi / 180) + 4 * np.sin(radius * 1.05) +
             13 * np.exp(-((radius - 126) / 4) ** 2))
    bands = [np.where(inside, steel + i, base + j) for i, j in ((-7, 0), (0, 1), (7, -7))]
    photo = Image.fromarray(np.stack(bands, axis=-1).clip(0, 255).astype("uint8"), "RGB")
    draw = ImageDraw.Draw(photo)
    draw.text((34, 64), "CHAINRING / FACE A", fill="#465151", font=ImageFont.load_default(size=15))
    draw.text((34, 408), "SIMULATED INSPECTION PHOTO", fill="#596764", font=ImageFont.load_default(size=11))
    return photo.size, png(photo), cfg


# Concise domain aliases for callers/tests describing the same operation.
compare = compare_teeth
compare_tooth = compare_teeth
compare_sectors = compare_teeth
tooth_comparison = compare_teeth
comparison_point = comparison_pair
