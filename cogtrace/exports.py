"""Preserve the real radial read, source markings and original in the exports."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json
import math

from PIL import Image, ImageDraw, ImageFont

from .rim import png


def trace_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("r_px", "x_px", "y_px", "luma", "metal"))
    for point in result["profile"]:
        writer.writerow((point["r"], point["x"], point["y"], f'{point["brightness"]:.3f}', int(point["metal"])))
    return buffer.getvalue().encode()


def teeth_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("tooth", "nominal_angle_deg", "status", "has_evidence",
                    "source_angle_deg", "radius_px", "x_px", "y_px",
                    "angular_error_deg", "score"))
    for tooth in result.get("teeth", []):
        evidence = tooth.get("evidence") or {}
        writer.writerow((
            tooth["index"], f'{tooth["nominal_angle"]:.6f}', tooth["status"],
            int(bool(tooth.get("has_evidence"))),
            "" if tooth.get("source_angle") is None else f'{tooth["source_angle"]:.6f}',
            "" if tooth.get("radius") is None else tooth["radius"],
            "" if tooth.get("x") is None else tooth["x"],
            "" if tooth.get("y") is None else tooth["y"],
            "" if tooth.get("angular_error_deg") is None else tooth["angular_error_deg"],
            "" if tooth.get("score") is None else tooth["score"],
        ))
    return buffer.getvalue().encode()


def proof(image, card, result):
    height, width = image.shape[:2]
    cfg = card["settings"]
    cx, cy = cfg["cx"], cfg["cy"]
    teeth = result.get("teeth", [])

    footer_font = ImageFont.load_default(size=14)
    small_font = ImageFont.load_default(size=12)
    missing = [str(tooth["index"]) for tooth in teeth if not tooth.get("has_evidence")]
    if teeth:
        assignment_line = (
            f'Tooth evidence {result.get("seen_count", 0)}/{len(teeth)}; '
            f'missing: {", ".join(missing) if missing else "none"}'
        )
    else:
        assignment_line = "Tooth one not adopted; nominal tooth numbering is unavailable"

    ray_line = f'Ray {result["angle"]:.2f} deg  Manual pitch {result["manual_pitch_deg"]:.2f} deg'
    if point := result["reading"]:
        detail = f'Edge {point["radius"]} px at source ({point["x"]}, {point["y"]})'
    else:
        detail = "No metal edge in the selected band"

    def wrap_text(text, font, max_width):
        words = text.split(", ")
        lines = []
        current = words[0] if words else text
        for word in words[1:]:
            candidate = current + ", " + word
            if draw_temp.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    temp = Image.new("RGB", (10, 10))
    draw_temp = ImageDraw.Draw(temp)
    assignment_lines = wrap_text(assignment_line, small_font, max(360, width - 28))
    footer_height = 58 + 19 * len(assignment_lines) + 12
    output = Image.new("RGB", (max(410, width), height + footer_height), "#212922")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)

    for radius in (cfg["inner"], cfg["outer"]):
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline="#567b73", width=2)

    # Evidence rays use the actual source angle, never the nominal angle.
    current_tooth = result.get("current_tooth") or {}
    current_index = current_tooth.get("index")
    for tooth in teeth:
        evidence = tooth.get("evidence")
        if not evidence:
            continue
        source_angle = math.radians(evidence.get("source_angle", evidence["angle"]))
        target = (cx + cfg["outer"] * math.cos(source_angle),
                  cy + cfg["outer"] * math.sin(source_angle))
        highlighted = tooth.get("index") == current_index
        draw.line((cx, cy, *target),
                  fill="#63c7e8" if highlighted else "#2f7f9b",
                  width=3 if highlighted else 1)
        x, y = evidence["x"], evidence["y"]
        draw.ellipse((x-4, y-4, x+4, y+4), fill="#63c7e8" if highlighted else "#2f7f9b")
        label = str(tooth["index"])
        draw.text((x + 6, max(2, y - 16)), label, font=small_font, fill="#bdeeff")

    angle = math.radians(result["angle"])
    target = cx + cfg["outer"] * math.cos(angle), cy + cfg["outer"] * math.sin(angle)
    draw.line((cx, cy, *target), fill="#be6f21", width=2)
    if point := result["reading"]:
        x, y = point["x"], point["y"]
        draw.ellipse((x-4, y-4, x+4, y+4), fill="#be6f21")

    y = height + 12
    draw.text((14, y), ray_line, font=footer_font, fill="#eaf1e7")
    y += 23
    draw.text((14, y), detail, font=small_font, fill="#e8ba85")
    y += 20
    for line in assignment_lines:
        draw.text((14, y), line, font=small_font, fill="#b9d8c8")
        y += 19
    return png(output)


def package(card, original, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("chainring.png", original)
        output.writestr("reading.json", json.dumps({
            "card": card,
            "reading": result["reading"],
            "angle": result["angle"],
            "manual_pitch_deg": result["manual_pitch_deg"],
            "anchor_angle": result.get("anchor_angle"),
            "first_tooth_angle": result.get("first_tooth_angle"),
            "current_tooth": result.get("current_tooth"),
            "teeth": result.get("teeth", []),
        }, ensure_ascii=False, indent=2))
        output.writestr("radial-profile.csv", trace_table(result))
        if result.get("teeth"):
            output.writestr("teeth.csv", teeth_table(result))
        output.writestr("ring-proof.png", proof(image, card, result))
    return buffer.getvalue()
