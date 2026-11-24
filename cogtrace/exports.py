"""Preserve the real radial read, source markings and original in the exports."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json
import math

from PIL import Image, ImageDraw

from .rim import png


def trace_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("r_px", "x_px", "y_px", "luma", "metal"))
    for point in result["profile"]:
        writer.writerow((point["r"], point["x"], point["y"], f'{point["brightness"]:.3f}', int(point["metal"])))
    return buffer.getvalue().encode()


def proof(image, card, result):
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(410, width), height+65), "#212922")
    output.paste(Image.fromarray(image), (0,0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    cx, cy = cfg["cx"], cfg["cy"]
    for radius in (cfg["inner"], cfg["outer"]):
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline="#567b73", width=2)
    angle = math.radians(result["angle"])
    target = cx + cfg["outer"] * math.cos(angle), cy + cfg["outer"] * math.sin(angle)
    draw.line((cx, cy, *target), fill="#be6f21", width=2)
    if point := result["reading"]:
        x, y = point["x"], point["y"]
        draw.ellipse((x-4, y-4, x+4, y+4), fill="#be6f21")
        detail = f'Edge {point["radius"]} px at source ({x}, {y})'
    else:
        detail = "No metal edge in the selected band"
    draw.text((14, height+14), f'Ray {result["angle"]:.2f} deg  Manual pitch {result["manual_pitch_deg"]:.2f} deg', fill="#eaf1e7")
    draw.text((14, height+35), detail, fill="#e8ba85")
    return png(output)


def package(card, original, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("chainring.png", original)
        output.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"],
                                                    "angle": result["angle"]}, ensure_ascii=False, indent=2))
        output.writestr("radial-profile.csv", trace_table(result))
        output.writestr("ring-proof.png", proof(image, card, result))
    return buffer.getvalue()
