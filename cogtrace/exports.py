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


def comparison_table(comparison):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("relative_angle_deg", "side", "reference_requested_angle_deg",
                     "reference_actual_angle_deg", "reference_r_px", "reference_x_px", "reference_y_px",
                     "suspect_requested_angle_deg", "suspect_actual_angle_deg",
                     "suspect_r_px", "suspect_x_px", "suspect_y_px",
                     "difference_ref_minus_suspect_px", "loss_positive_px", "material_loss"))

    def edge_fields(edge):
        if not edge:
            return ("", "", "", "")
        return (f'{edge["actual_angle"]:.6f}', edge["radius"], edge["x"], edge["y"])

    for row in comparison["rows"]:
        ref = row["reference"]
        suspect = row["suspect"]
        ref_actual, ref_r, ref_x, ref_y = edge_fields(ref)
        sus_actual, sus_r, sus_x, sus_y = edge_fields(suspect)
        writer.writerow((
            f'{row["relative_angle"]:.6f}', row["side"],
            f'{ref["requested_angle"]:.6f}' if ref else "", ref_actual, ref_r, ref_x, ref_y,
            f'{suspect["requested_angle"]:.6f}' if suspect else "", sus_actual, sus_r, sus_x, sus_y,
            "" if row["difference_px"] is None else row["difference_px"],
            "" if row["loss_px"] is None else row["loss_px"],
            "" if row["material_loss"] is None else int(row["material_loss"]),
        ))
    return buffer.getvalue().encode()


def _proof_font(size=14):
    try:
        from PIL import ImageFont
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except (OSError, ImportError):
        return ImageFont.load_default(size=size)


def _draw_compare_edge(draw, cfg, edge, color, tag, font):
    if not edge:
        return
    cx, cy = cfg["cx"], cfg["cy"]
    requested = math.radians(edge.get("requested_angle", edge.get("angle", 0.0)))
    outer = cfg["outer"]
    draw.line((cx, cy, cx + outer * math.cos(requested), cy + outer * math.sin(requested)),
              fill=color, width=1)
    x, y = edge["x"], edge["y"]
    draw.line((cx, cy, x, y), fill=color, width=2)
    draw.ellipse((x - 8, y - 8, x + 8, y + 8), outline="#f4fbf5", width=3)
    draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=color, width=3)
    draw.rectangle((x + 9, y - 22, x + 34, y - 4), fill="#1d2621")
    draw.text((x + 14, y - 21), tag, fill=color, font=font)


def proof(image, card, result):
    height, width = image.shape[:2]
    comparison = result.get("comparison")
    compare_lines = 6 if comparison else 0
    footer_height = 65 + 19 * compare_lines
    output_width = max(780 if comparison else 410, width)
    output = Image.new("RGB", (output_width, height + footer_height), "#212922")
    output.paste(Image.fromarray(image), (0,0))
    draw = ImageDraw.Draw(output)
    small = _proof_font(13)
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
    draw.text((14, height+14), f'Ray {result["angle"]:.2f} deg  Manual pitch {result["manual_pitch_deg"]:.2f} deg',
              fill="#eaf1e7")
    draw.text((14, height+35), detail, fill="#e8ba85")

    if comparison:
        ref_color = "#42e695"
        suspect_color = "#63b8ff"
        adopted = comparison.get("adopted_offset_deg", comparison.get("offset_deg", 0.0))
        reference_center = comparison.get("reference_selected_angle",
                                          comparison.get("reference_angle", cfg["angle"]))
        suspect_center = comparison.get("suspect_selected_angle",
                                       comparison.get("suspect_angle", cfg["angle"]))
        aligned_suspect_center = suspect_center + adopted
        half = comparison.get("half_pitch_deg", comparison.get("sector_half_width_deg",
                                                                180.0 / cfg["teeth"]))
        # Thin sector-boundary rays make the two selected half-pitch windows auditable.
        for center, color in ((comparison["reference_selected_angle"], ref_color),
                              (aligned_suspect_center, suspect_color)):
            for boundary in (center - half, center + half):
                radians = math.radians(boundary)
                end = (cx + cfg["outer"] * math.cos(radians),
                       cy + cfg["outer"] * math.sin(radians))
                draw.line((cx, cy, *end), fill=color, width=1)

        pair = comparison.get("point") or comparison.get("comparison_point") or {}
        _draw_compare_edge(draw, cfg, pair.get("reference") or pair.get("reference_reading"),
                           ref_color, "R", small)
        _draw_compare_edge(draw, cfg, pair.get("suspect") or pair.get("suspect_reading"),
                           suspect_color, "T", small)

        top = height + 63
        relative = pair.get("relative_angle", pair.get("comparison_angle", 0.0))
        draw.text((14, top),
                  f'COMPARE t={relative:.3f} deg  offset={adopted:.3f} deg  '
                  f'H={reference_center:.3f}  T={suspect_center:.3f}',
                  fill="#eaf1e7", font=small)

        def source_line(label, color, edge):
            if not edge:
                return f'{label}: no real edge; blank (not counted as loss)'
            actual = edge.get("actual_angle", edge.get("source_angle", 0.0))
            return (f'{label}: actual angle {actual:.3f} deg; '
                    f'source pixel ({edge.get("x")}, {edge.get("y")}); r={edge.get("radius")} px')

        draw.text((14, top + 20), source_line("REF", ref_color, pair.get("reference")),
                  fill=ref_color, font=small)
        draw.text((14, top + 40), source_line("TGT", suspect_color, pair.get("suspect")),
                  fill=suspect_color, font=small)
        if pair.get("complete"):
            difference = pair["difference_px"]
            draw.text((14, top + 60),
                      f'difference REF-TGT={difference} px; positive loss={pair["loss_px"]} px',
                      fill="#ffd166" if pair["material_loss"] else "#c9d6c8", font=small)
            verdict = "POSITIVE DIFFERENCE: MATERIAL LOSS" if pair["material_loss"] \
                else "not a positive difference; no material-loss mark"
            draw.text((14, top + 78), verdict,
                      fill="#ff8a5c" if pair["material_loss"] else "#c9d6c8", font=small)
        else:
            draw.text((14, top + 60),
                      "One side lacks a real edge reading; blank, not material loss.",
                      fill="#c9d6c8", font=small)
    return png(output)


def package(card, original, image, result):
    buffer = BytesIO()
    comparison = result.get("comparison")
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("chainring.png", original)
        output.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"],
                                                    "angle": result["angle"],
                                                    "comparison": comparison},
                                                   ensure_ascii=False, indent=2))
        output.writestr("radial-profile.csv", trace_table(result))
        output.writestr("ring-proof.png", proof(image, card, result))
        if comparison:
            output.writestr("tooth-comparison.json",
                            json.dumps(comparison, ensure_ascii=False, indent=2))
            output.writestr("tooth-comparison.csv", comparison_table(comparison))
    return buffer.getvalue()
