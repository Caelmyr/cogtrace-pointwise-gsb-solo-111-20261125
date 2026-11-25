"""Read original dark-material outlines in a user-calibrated radial band."""

from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid, integer, number

from .teeth import (angle_delta, assign_teeth, layout_report, norm_angle,
                    tooth_at_angle)


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


def anchor_setting(value):
    """Accept the canonical key and a few direct aliases used by clients."""
    aliases = ("first_tooth_angle", "anchor_angle", "tooth_one_angle",
               "number_one_angle", "adopted_angle")
    raw = None
    found = False
    for key in aliases:
        if key in value:
            raw = value[key]
            found = True
            break
    if not found and "anchor" in value:
        anchor = value["anchor"]
        if isinstance(anchor, dict):
            raw = anchor.get("angle", anchor.get("source_angle", anchor.get("first_tooth_angle")))
        else:
            raw = anchor
        found = True
    if not found or raw is None or raw is False or raw == "":
        return None
    if isinstance(raw, dict):
        raw = raw.get("angle", raw.get("source_angle"))
    return number(raw, "一号齿方向", 0, 360) % 360


def settings(value, size):
    width, height = size
    inner = integer(value.get("inner"), "内环半径", 2, max(size) - 3)
    first_tooth_angle = anchor_setting(value)
    return {
        "cx": number(value.get("cx"), "盘心 X", 0, width - 1),
        "cy": number(value.get("cy"), "盘心 Y", 0, height - 1),
        "inner": inner,
        "outer": integer(value.get("outer"), "外环半径", inner + 2, max(size)),
        "cutoff": integer(value.get("cutoff"), "金属亮度上限", 1, 254),
        "angle": number(value.get("angle"), "核查角度", 0, 360) % 360,
        "teeth": integer(value.get("teeth"), "手填齿数", 6, 120),
        "first_tooth_angle": first_tooth_angle,
        "anchor_angle": first_tooth_angle,
    }


def public_card(card):
    """Add read-only aliases without changing the stored card schema."""
    presented = dict(card)
    config = dict(card.get("settings", {}))
    anchor = config.get("first_tooth_angle")
    if anchor is not None:
        anchor = norm_angle(anchor)
        config["first_tooth_angle"] = anchor
        config["anchor_angle"] = anchor
    else:
        config["anchor_angle"] = None
    presented["settings"] = config
    presented["anchor_angle"] = anchor
    presented["first_tooth_angle"] = anchor
    presented["adopted"] = anchor is not None
    presented["anchor"] = None if anchor is None else {
        "adopted": True, "tooth": 1, "angle": anchor, "first_tooth_angle": anchor
    }
    return presented


def defaults(size):
    width, height = size
    return settings({"cx": width // 2, "cy": height // 2, "inner": max(2, int(min(size) * .27)),
                     "outer": int(min(size) * .48), "cutoff": 140, "angle": 0, "teeth": 24}, size)


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
    return {"angle": angle, "r": r, "x": x, "y": y, "brightness": levels, "metal": metal}


def edge(trace):
    candidates = np.flatnonzero(trace["metal"])
    if not len(candidates):
        return None
    index = candidates[-1]
    return {"radius": int(trace["r"][index]), "x": int(trace["x"][index]), "y": int(trace["y"][index])}


def solid_edge(trace):
    """Find the outer end of the dark run connected to the inner band.

    The ordinary edge() deliberately reports the outermost dark pixel for the
    manual ray readout.  Tooth evidence additionally has to reject a detached
    dark spot, so an isolated terminal run is not accepted as the tooth edge.
    """
    metal = trace["metal"]
    levels = trace["brightness"]
    hits = np.flatnonzero(metal)
    if not len(hits):
        return None

    raw_index = int(hits[-1])
    run_start = raw_index
    while run_start > 0 and bool(metal[run_start - 1]):
        run_start -= 1
    terminal_run = raw_index - run_start + 1
    width = len(metal)
    connect_tolerance = max(2, int(round(width * 0.08)))

    index = None
    if run_start <= connect_tolerance:
        index = raw_index
    else:
        split_at = np.flatnonzero(np.diff(hits) > 1)
        runs = np.split(hits, split_at + 1)
        for run in reversed(runs):
            if int(run[0]) <= connect_tolerance:
                index = int(run[-1])
                break
        if index is None and terminal_run >= max(6, int(round(width * 0.35))):
            # Conservative fallback for a band whose first samples are bright.
            index = raw_index
    if index is None:
        return None

    outside = levels[index + 1:min(width, index + 4)]
    inside = levels[max(0, index - 3):index + 1]
    if outside.size:
        contrast = float(outside.mean() - inside.mean())
    else:
        contrast = max(18.0, 220.0 - float(inside.mean()) if inside.size else 40.0)
    clarity = max(0.0, min(1.0, (contrast - 8.0) / 65.0))
    return {"index": index, "raw_index": raw_index, "contrast": contrast, "clarity": clarity}


def detect_tips(image, config, angular_step=0.25):
    """Detect circular tip candidates using only radial rays in the band."""
    teeth = max(6, int(config["teeth"]))
    pitch = 360.0 / teeth
    count = max(720, int(round(360.0 / angular_step)))
    step = 360.0 / count
    angles = np.arange(count, dtype=float) * step
    radii = np.full(count, np.nan, dtype=float)
    records = [None] * count
    height, width = image.shape[:2]

    for index, requested_angle in enumerate(angles):
        trace = ray(image, float(requested_angle), config)
        qualified = solid_edge(trace)
        if qualified is None:
            continue
        edge_index = qualified["index"]
        radius = int(trace["r"][edge_index])
        x = int(trace["x"][edge_index])
        y = int(trace["y"][edge_index])
        if not (0 <= x < width and 0 <= y < height):
            continue
        source_angle = math.degrees(math.atan2(y - config["cy"], x - config["cx"])) % 360.0
        radii[index] = radius
        records[index] = {
            "id": index,
            "angle": source_angle,
            "ray_angle": float(requested_angle),
            "radius": radius,
            "x": x,
            "y": y,
            "clarity": qualified["clarity"],
            "contrast": qualified["contrast"],
        }

    valid = ~np.isnan(radii)
    if not np.any(valid):
        return []
    fallback_radius = config["inner"] - 1.0
    filled = np.where(valid, radii, fallback_radius)
    valid_radii = radii[valid]
    outer_level = float(np.percentile(valid_radii, 92))
    root_level = float(np.percentile(valid_radii, 12))
    radial_depth = max(2.0, outer_level - root_level)
    minimum_tip_radius = outer_level - 0.45 * radial_depth

    peak_half_deg = max(0.5, min(1.25, pitch * 0.08))
    peak_window = max(1, int(round(peak_half_deg / step)))
    is_peak = np.zeros(count, dtype=bool)
    for index in range(count):
        value = filled[index]
        is_peak[index] = all(
            value >= filled[(index + offset) % count]
            for offset in range(-peak_window, peak_window + 1)
            if offset
        )

    if not np.any(is_peak):
        return []

    starts = [index for index in range(count)
              if is_peak[index] and not is_peak[(index - 1) % count]]
    groups: list[list[int]] = []
    if not starts:
        groups = [list(range(count))]
    for start in starts:
        group = []
        index = start
        while is_peak[index] and len(group) <= count:
            group.append(index)
            index = (index + 1) % count
            if index == start:
                break
        if group:
            groups.append(group)

    shoulder_bins = max(1, int(round(max(0.35, pitch * 0.08) / step)))
    search_bins = max(shoulder_bins + 1, int(round(pitch * 0.45 / step)))
    min_fallback = max(2, int(round((config["outer"] - config["inner"]) * 0.05)))
    candidates = []

    for group in groups:
        if len(group) % 2:
            representative = group[len(group) // 2]
        else:
            left = group[len(group) // 2 - 1]
            right = group[len(group) // 2]
            representative = left if filled[left] >= filled[right] else right
        record = records[representative]
        if record is None:
            continue
        center = representative
        left_values = [
            filled[(center + offset) % count]
            for offset in range(-search_bins, -shoulder_bins + 1)
        ]
        right_values = [
            filled[(center + offset) % count]
            for offset in range(shoulder_bins, search_bins + 1)
        ]
        if not left_values or not right_values:
            continue
        fallback_left = int(record["radius"] - min(left_values))
        fallback_right = int(record["radius"] - min(right_values))
        if fallback_left < min_fallback or fallback_right < min_fallback:
            continue
        if record["radius"] + 0.5 < minimum_tip_radius:
            continue

        envelope_strength = max(0.0, min(1.0, (record["radius"] - root_level) / radial_depth))
        side_strength = min(1.0, min(fallback_left, fallback_right) / 12.0)
        strength = 0.65 * envelope_strength + 0.35 * side_strength
        candidate = dict(record)
        candidate.update({
            "fallback_left_px": fallback_left,
            "fallback_right_px": fallback_right,
            "strength": strength,
            "envelope_strength": envelope_strength,
        })
        candidates.append(candidate)

    # Quantised rays can split one broad tip into adjacent one-pixel plateaus.
    # Merge only sub-pitch fragments; split tips around a chipped tooth remain.
    merge_deg = max(0.75, pitch * 0.25)
    candidates.sort(key=lambda item: (
        -int(item["radius"]), -float(item["clarity"]),
        -min(int(item["fallback_left_px"]), int(item["fallback_right_px"])),
        float(item["angle"])
    ))
    merged: list[dict] = []
    for candidate in candidates:
        if all(abs(angle_delta(candidate["angle"], kept["angle"])) >= merge_deg for kept in merged):
            merged.append(candidate)
    merged.sort(key=lambda item: int(item["id"]))
    return merged


# Descriptive aliases for callers/tests that name the operation differently.
detect_candidates = detect_tips
find_tips = detect_tips
build_assignments = layout_report


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
    candidates = detect_tips(image, config)
    teeth_layout = layout_report(
        config["teeth"], config.get("first_tooth_angle"), candidates, config["angle"]
    )
    current_tooth = teeth_layout.get("current_tooth")
    if current_tooth is None and teeth_layout["adopted"]:
        current_tooth = tooth_at_angle(teeth_layout["teeth"], config.get("first_tooth_angle"), config["angle"])
    return {"reading": edge(active), "angle": config["angle"], "manual_pitch_deg": step,
            "profile": profile, "sweep": sweep, "candidates": candidates,
            **teeth_layout, "current_tooth": current_tooth}


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
