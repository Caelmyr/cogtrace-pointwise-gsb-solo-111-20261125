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
