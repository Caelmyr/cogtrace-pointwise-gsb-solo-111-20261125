"""Connect the chainring inspection desk to the photo preparation workspace."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, number, object_value

from . import exports, rim
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
        return jsonify(cards.update(key, object_value(request.get_json(silent=True), "核查卡设置"))
                       if request.method == "PATCH" else cards.read(key))

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def optional_number(source, names, label):
        for name in names:
            if name in source and source[name] not in (None, ""):
                return number(source[name], label)
        return None

    def comparison_spec(card, source):
        names = ("reference_angle", "healthy_angle", "intact_angle", "good_angle",
                 "ref_angle", "reference", "reference_tooth_angle", "healthy_tooth_angle",
                 "suspect_angle", "candidate_angle", "target_angle", "checked_angle",
                 "inspected_angle", "damaged_angle", "worn_angle", "bad_angle",
                 "defect_angle", "suspect_tooth_angle", "suspect")
        requested = any(name in source and source[name] not in (None, "") for name in names)
        compare_flag = str(source.get("compare", "")).lower() in {"1", "true", "yes", "compare"}
        nested = source.get("comparison") if hasattr(source, "get") else None
        if isinstance(nested, dict):
            source = {**dict(source), **nested}
            requested = True
        if not requested and not compare_flag:
            saved = card.get("comparison")
            if isinstance(saved, dict):
                return comparison_spec(card, saved)
            return None
        config = card["settings"]
        reference = optional_number(source, ("reference_angle", "healthy_angle", "intact_angle",
                                             "good_angle", "ref_angle", "reference_tooth_angle",
                                             "healthy_tooth_angle", "reference"),
                                    "完好齿选角")
        suspect = optional_number(source, ("suspect_angle", "candidate_angle", "target_angle",
                                           "checked_angle", "inspected_angle", "damaged_angle",
                                           "worn_angle", "bad_angle", "defect_angle",
                                           "suspect_tooth_angle", "suspect"), "待查齿选角")
        if reference is None:
            reference = optional_number(source, ("healthy", "ref", "intact", "good"), "完好齿选角")
        if suspect is None:
            suspect = optional_number(source, ("candidate", "target", "damaged", "worn", "bad"),
                                      "待查齿选角")
        if reference is None and compare_flag:
            reference = config["angle"]
        if suspect is None and compare_flag:
            suspect = config["angle"]
        if reference is None or suspect is None:
            raise Invalid("请先记录完好齿选角和待查齿选角")
        offset = optional_number(source, ("offset", "angle_offset", "adopted_offset",
                                          "alignment_offset", "rotation_offset", "rotation",
                                          "alignment", "shift", "angle_shift"), "采用角偏")
        point_angle = optional_number(source, ("comparison_angle", "compare_angle", "relative_angle",
                                               "relative", "pair_angle", "point_angle", "at_angle",
                                               "angle_offset_point", "check_angle"), "对照角")
        absolute_angle = optional_number(source, ("absolute_comparison_angle", "absolute_angle",
                                                  "reference_source_angle", "source_check_angle"),
                                         "绝对对照角")
        if absolute_angle is not None:
            point_angle = rim.signed_angle_delta(absolute_angle, reference)
        elif str(source.get("angle_frame", "")).lower() in {"absolute", "source", "reference_absolute"} \
                and point_angle is not None:
            point_angle = rim.signed_angle_delta(point_angle, reference)
        return {"reference_angle": reference, "suspect_angle": suspect,
                "offset": offset, "point_angle": point_angle}

    def measurement(key, source=None):
        source = request.args if source is None else source
        revision = source.get("revision") if hasattr(source, "get") else None
        card = cards.read(key, revision)
        image = rim.pixels(cards.photo(key))
        result = rim.report(image, card["settings"])
        spec = comparison_spec(card, source)
        if spec is not None:
            result["comparison"] = rim.compare_teeth(image, card["settings"], **spec)
        return card, image, result

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    def compare_source():
        if request.method == "POST":
            body = request.get_json(silent=True)
            source = {**request.args, **(body if isinstance(body, dict) else {})}
            if isinstance(body, dict) and isinstance(body.get("comparison"), dict):
                source = {**source, **body["comparison"]}
            return source
        return request.args

    @api.route("/cards/<key>/compare", methods=["GET", "POST"])
    @api.route("/cards/<key>/comparison", methods=["GET", "POST"])
    @api.route("/cards/<key>/teeth-compare", methods=["GET", "POST"])
    def compare_json(key):
        source = compare_source()
        card, _, result = measurement(key, source)
        comparison = result["comparison"]
        return jsonify(revision=card["revision"], **comparison)

    @api.route("/cards/<key>/compare/point", methods=["GET", "POST"])
    @api.route("/cards/<key>/comparison-point", methods=["GET", "POST"])
    def comparison_point_json(key):
        source = compare_source()
        card, _, result = measurement(key, source)
        comparison = result["comparison"]
        return jsonify(revision=card["revision"], **comparison["point"])

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

    @api.get("/cards/<key>/export/comparison.csv")
    def comparison_csv(key):
        _, _, result = measurement(key)
        comparison = result.get("comparison")
        if comparison is None:
            raise Invalid("请先给出完好齿和待查齿选角并采用对照")
        return download(exports.comparison_table(comparison), "text/csv", "tooth-comparison.csv")

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
