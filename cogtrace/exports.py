"""Preserve the real radial read, source markings and original in the exports."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json
import math

from PIL import Image, ImageDraw

from . import bore
from .rim import png


def trace_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("r_px", "x_px", "y_px", "luma", "metal"))
    for point in result["profile"]:
        writer.writerow((point["r"], point["x"], point["y"], f'{point["brightness"]:.3f}', int(point["metal"])))
    return buffer.getvalue().encode()


COMPASS_COLOR = "#ff4d4f"
WALL_COLOR = "#ff2d55"
RAYWALL_COLOR = "#36d6e7"


def _cross(draw, x, y, color, arm=7, width=2):
    draw.line((x - arm, y, x + arm, y), fill=color, width=width)
    draw.line((x, y - arm, x, y + arm), fill=color, width=width)


def _dot(draw, x, y, fill, outline="#ffffff", radius=4):
    draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                 fill=fill, outline=outline, width=2)


def draw_compass(draw, image, card, result):
    """Bake the adopted compass circle, its center and real wall points."""
    compass = result.get("compass") if isinstance(result, dict) else None
    if compass is None and card.get("compass"):
        try:
            compass = bore.adopted_marks(image, card["settings"], card["compass"])
        except Exception:
            compass = None
    if not compass:
        return []

    gx, gy = compass["gx"], compass["gy"]
    radius = float(compass["radius"])
    box = (gx - radius, gy - radius, gx + radius, gy + radius)
    draw.ellipse(box, outline=COMPASS_COLOR, width=2)
    _cross(draw, gx, gy, COMPASS_COLOR, arm=8, width=2)
    draw.ellipse((gx - 3, gy - 3, gx + 3, gy + 3), fill=COMPASS_COLOR)
    draw.text((gx + 10, gy - 22), "compass center", fill=COMPASS_COLOR)

    for point in compass.get("wall_points", []):
        _dot(draw, point["x"], point["y"], WALL_COLOR)

    direction = compass.get("direction") or {}
    wall = direction.get("wall")
    if wall:
        draw.line((gx, gy, wall["x"], wall["y"]), fill=RAYWALL_COLOR, width=1)
        _dot(draw, wall["x"], wall["y"], RAYWALL_COLOR, outline="#06323a", radius=5)
    return compass_lines(compass)


def compass_lines(compass):
    lines = [
        f'Compass center ({compass["gx"]}, {compass["gy"]})  '
        f'R {float(compass["radius"]):g} px  D {float(compass["diameter"]):g} px  '
        f'offset {compass.get("offset", 0):.2f} px',
    ]
    tight = compass.get("tightest")
    if tight:
        lines.append(
            f'Tightest wall ({tight["x"]}, {tight["y"]})  '
            f'd {tight["distance"]:.2f} px  margin {tight["margin"]:.2f} px  '
            f'@{tight["angle"]:.1f} deg from compass')
    direction = compass.get("direction") or {}
    wall = direction.get("wall")
    if wall and direction.get("margin") is not None:
        lines.append(
            f'Ray {direction["angle"]:.2f} deg: wall ({wall["x"]}, {wall["y"]})  '
            f'edge margin {direction["margin"]:.2f} px')
    else:
        reason = direction.get("reason") or "no wall"
        lines.append(f'Ray {direction.get("angle", 0):.2f} deg: no hole wall ({reason}); margin left blank')
    if compass.get("fits_current_metal") is False:
        lines.append("WARNING: adopted compass overlaps metal under current settings - review")
    elif compass.get("review"):
        lines.append("REVIEW: opening reaches image/inner boundary; closed through-hole not verified")
    return lines


def proof(image, card, result):
    height, width = image.shape[:2]
    has_compass = bool(card.get("compass")) or bool(isinstance(result, dict) and result.get("compass"))
    footer = 128 if has_compass else 65
    output = Image.new("RGB", (max(410, width), height + footer), "#212922")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    cx, cy = cfg["cx"], cfg["cy"]
    for radius in (cfg["inner"], cfg["outer"]):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="#567b73", width=2)
    angle = math.radians(result["angle"])
    target = cx + cfg["outer"] * math.cos(angle), cy + cfg["outer"] * math.sin(angle)
    draw.line((cx, cy, *target), fill="#be6f21", width=2)
    if point := result["reading"]:
        x, y = point["x"], point["y"]
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#be6f21")
        detail = f'Edge {point["radius"]} px at source ({x}, {y})'
    else:
        detail = "No metal edge in the selected band"
    draw.text((14, height + 12), f'Ray {result["angle"]:.2f} deg  Manual pitch {result["manual_pitch_deg"]:.2f} deg', fill="#eaf1e7")
    draw.text((14, height + 31), detail, fill="#e8ba85")
    extra = draw_compass(draw, image, card, result)
    top = height + 52
    for index, line in enumerate(extra[:4]):
        draw.text((14, top + index * 16), line, fill="#ffd9d9" if index else "#ffb3b5")
    return png(output)


def package(card, original, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("chainring.png", original)
        output.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"],
                                                    "angle": result["angle"],
                                                    "compass": result.get("compass")},
                                                   ensure_ascii=False, indent=2))
        try:
            bore_report = bore.inspect(image, card["settings"], card.get("compass"))
            output.writestr("bore.json", json.dumps(bore_report, ensure_ascii=False, indent=2))
        except Exception:
            pass
        output.writestr("radial-profile.csv", trace_table(result))
        output.writestr("ring-proof.png", proof(image, card, result))
    return buffer.getvalue()
