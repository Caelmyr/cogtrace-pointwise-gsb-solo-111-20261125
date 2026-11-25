"""Connect the chainring inspection desk to the photo preparation workspace."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, number, object_value

from . import bore, exports, rim
from .store import Cards


def download(data, mime, filename):
    return send_file(BytesIO(data), mimetype=mime, max_age=0, download_name=filename, as_attachment=True)


def create_app(directory=None):
    root = Path(directory or os.environ.get("COGTRACE_DATA", ".cogtrace-data")).resolve()
    desk = preparation_app(root / "prepare")
    cards = Cards(root / "cards")
    api = Blueprint("cogtrace", __name__, url_prefix="/cogtrace")

    @desk.get("/")
    def home():
        return render_template("cogtrace.html")

    @api.get("/health")
    def health():
        return jsonify(status="ok", app="cogtrace")

    @api.get("/cards")
    def listing():
        return jsonify(cards=cards.list())

    @api.post("/cards")
    def create():
        request.max_content_length = 20 * 1024 * 1024
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise Invalid("请选择齿盘原片")
        size, image = rim.decode(upload.stream.read(rim.MAX_IMAGE_BYTES + 1))
        return jsonify(cards.create(request.form.get("name", ""), Path(upload.filename).name[:140],
                                    size, image, rim.defaults(size))), 201

    @api.post("/practice")
    def practice():
        return jsonify(cards.demo()), 201

    @api.route("/cards/<key>", methods=["GET", "PATCH"])
    def card(key):
        if request.method == "PATCH":
            body = object_value(request.get_json(silent=True), "核查卡设置")
            if "compass" in body:
                if "settings" in body or "name" in body:
                    updated = cards.update(key, body)
                    body["revision"] = updated["revision"]
                return jsonify(patch_compass(key, body))
            return jsonify(cards.update(key, body))
        return jsonify(cards.read(key))

    def patch_compass(key, body):
        """PATCH /cards/<key> with a top-level ``compass`` adoption/removal."""
        revision = body.get("revision")
        value = body.get("compass")
        if value is None or value is False:
            return cards.save_compass(key, None, revision)
        incoming = object_value(value, "圆规数据")
        current = cards.read(key, revision)
        image = rim.pixels(cards.photo(key))
        compass = bore.resolve_adoption(image, current["settings"], incoming)
        return cards.save_compass(key, compass, current["revision"])

    @api.get("/cards/<key>/bore")
    def bore_report(key):
        card = cards.read(key, request.args.get("revision"))
        image = rim.pixels(cards.photo(key))
        return jsonify(bore.inspect(image, card["settings"], card.get("compass")))

    @api.get("/cards/<key>/compass/ray")
    def compass_ray(key):
        """Live edge-to-wall margin at an arbitrary angle without saving."""
        card = cards.read(key, request.args.get("revision"))
        compass = card.get("compass")
        if not compass:
            raise Invalid("尚未采用圆规")
        angle = number(request.args.get("angle", card["settings"]["angle"]), "方向角度", 0, 360) % 360
        image = rim.pixels(cards.photo(key))
        seg = bore.segment(image, card["settings"])
        return jsonify(bore.directional_wall(seg, compass, angle))

    def adopt_from_request(key):
        body = request.get_json(silent=True)
        if body is None:
            body = {**request.args.to_dict(), **request.form.to_dict()}
        body = object_value(body, "圆规参数")
        revision = body.get("revision", request.args.get("revision"))
        current = cards.read(key, revision)
        image = rim.pixels(cards.photo(key))
        compass = bore.resolve_adoption(image, current["settings"], body)
        return cards.save_compass(key, compass, current["revision"])

    @api.post("/cards/<key>/compass")
    def compass_adopt(key):
        return jsonify(adopt_from_request(key))

    @api.put("/cards/<key>/compass")
    def compass_put(key):
        return jsonify(adopt_from_request(key))

    @api.post("/cards/<key>/compass/adopt")
    def compass_adopt_alias(key):
        return jsonify(adopt_from_request(key))

    @api.post("/cards/<key>/bore/adopt")
    def bore_adopt_alias(key):
        return jsonify(adopt_from_request(key))

    @api.delete("/cards/<key>/compass")
    def compass_clear(key):
        body = request.get_json(silent=True) or {}
        revision = body.get("revision", request.args.get("revision"))
        return jsonify(cards.save_compass(key, None, revision))

    @api.post("/cards/<key>/compass/clear")
    def compass_clear_alias(key):
        body = request.get_json(silent=True) or {}
        revision = body.get("revision", request.args.get("revision"))
        return jsonify(cards.save_compass(key, None, revision))

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def measurement(key):
        card = cards.read(key, request.args.get("revision"))
        image = rim.pixels(cards.photo(key))
        result = rim.report(image, card["settings"])
        try:
            inspection = bore.inspect(image, card["settings"], card.get("compass"))
            result["bore"] = inspection
            result["compass"] = inspection.get("adopted") if card.get("compass") else None
        except (Invalid, KeyError, IndexError, ValueError, TypeError):
            result["bore"] = None
            result["compass"] = None
        if result.get("compass"):
            direction = result["compass"].get("direction") or {}
            # Convenience aliases for the same-angle edge-to-wall allowance.
            result["compass_center"] = {"gx": result["compass"]["gx"], "gy": result["compass"]["gy"]}
            result["compass_radius"] = result["compass"]["radius"]
            result["compass_margin"] = direction.get("margin")
            result["hole_wall"] = direction.get("wall")
        else:
            result["compass_margin"] = None
            result["hole_wall"] = None
        return card, image, result

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        return jsonify(rim.point(rim.pixels(cards.photo(key)), x, y, card["settings"]))

    @api.get("/cards/<key>/export/profile.csv")
    def profile(key):
        _, _, result = measurement(key)
        return download(exports.trace_table(result), "text/csv", "radial-profile.csv")

    @api.get("/cards/<key>/export/proof.png")
    def proof(key):
        card, image, result = measurement(key)
        return download(exports.proof(image, card, result), "image/png", "ring-proof.png")

    @api.get("/cards/<key>/export/observation.zip")
    def bundle(key):
        card, image, result = measurement(key)
        package = exports.package(card, cards.photo(key).read_bytes(), image, result)
        return download(package, "application/zip", f"cogtrace-r{card['revision']}.zip")

    @api.post("/cards/<key>/prepare")
    def prepare(key):
        card = cards.read(key, request.args.get("revision"))
        image = rim.pixels(cards.photo(key)).astype("float32") / 255
        services = desk.extensions
        asset = services["assets"].put(image, card["photo_name"])
        project = services["store"].create(f'{card["name"]} · 原片准备')
        services["frames"].add(project["id"], project["revision"], [asset["id"]])
        return jsonify(url=url_for("index", project=project["id"])), 201

    desk.register_blueprint(api)
    return desk
