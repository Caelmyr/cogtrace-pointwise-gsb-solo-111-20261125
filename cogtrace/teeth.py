"""Evidence-backed mapping of observed tips to manually numbered teeth."""

from __future__ import annotations

import math
from typing import Any


def norm_angle(angle: float) -> float:
    return float(angle) % 360.0


def angle_delta(angle: float, reference: float) -> float:
    """Signed shortest angular difference, positive clockwise."""
    return (float(angle) - float(reference) + 180.0) % 360.0 - 180.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _normalise_candidate(candidate: Any, candidate_id: int) -> dict[str, Any]:
    if isinstance(candidate, (int, float)):
        candidate = {"angle": float(candidate)}
    elif isinstance(candidate, (tuple, list)):
        candidate = {"angle": candidate[0] if candidate else 0.0}
        if len(candidate) > 1:
            candidate["radius"] = candidate[1]
    if not isinstance(candidate, dict):
        raise ValueError("tooth candidate must be an object or angle")

    source = candidate.get("source_angle")
    if source is None:
        source = candidate.get("angle", candidate.get(
            "angle_deg", candidate.get("deg", candidate.get("theta", 0.0))))
    angle = norm_angle(source)
    result = dict(candidate)
    edge = result.get("edge")
    if isinstance(edge, dict):
        for key in ("x", "y", "radius"):
            if result.get(key) is None and edge.get(key) is not None:
                result[key] = edge[key]
        if result.get("radius") is None and edge.get("r") is not None:
            result["radius"] = edge["r"]
    if result.get("radius") is None and result.get("r") is not None:
        result["radius"] = result["r"]
    result["angle"] = angle
    result.setdefault("id", candidate_id)
    return result


def _gap_bonus(delta_unwrapped: float, pitch: float) -> float | None:
    # A non-positive gap would mean clockwise order has been reversed.
    if delta_unwrapped <= 1e-8:
        return None
    pitch_error = abs(delta_unwrapped - pitch) / pitch
    return 0.08 * _clamp(1.0 - pitch_error / 0.6, 0.0, 1.0)


def assign_teeth(count: int, anchor_angle: float | None, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign unique observed tips to clockwise tooth positions.

    Tooth 1 is at ``anchor_angle``.  A candidate can support a position only
    when its shortest circular distance from the nominal angle is at most 60%
    of the pitch.  The dynamic program keeps candidate identities unique and
    keeps matched source angles in clockwise order, including the join between
    the last and first positions around 0/360 degrees.
    """
    count = int(count)
    pitch = 360.0 / count
    tolerance = pitch * 0.6
    anchor = norm_angle(anchor_angle or 0.0)
    nominal = [norm_angle(anchor + index * pitch) for index in range(count)]
    raw_candidates = [_normalise_candidate(item, index) for index, item in enumerate(candidates or [])]

    options: list[list[dict[str, Any]]] = []
    for tooth_index in range(count):
        tooth_options: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            error = angle_delta(candidate["angle"], nominal[tooth_index])
            magnitude = abs(error)
            if magnitude > tolerance + 1e-8:
                continue

            angle_fit = _clamp(1.0 - magnitude / tolerance)
            clarity = _clamp(candidate.get("clarity", candidate.get("quality", 0.72)))
            strength = _clamp(candidate.get("strength", 0.55))
            own_score = 0.55 * angle_fit + 0.30 * clarity + 0.15 * strength
            if tooth_index == 0:
                # Adoption is an explicit user decision; resolve circular
                # boundary ambiguity in favour of position one.
                own_score = min(1.0, own_score + 0.10)
            tooth_options.append({
                "candidate": candidate,
                "candidate_id": candidate["id"],
                "unwrapped_angle": tooth_index * pitch + error,
                "angular_error": magnitude,
                "own_score": own_score,
            })
        tooth_options.sort(key=lambda item: (-item["own_score"], item["angular_error"], str(item["candidate_id"])))
        options.append(tooth_options)

    def run_case(fixed_first_option: int | None):
        # None means tooth one is forced missing; an integer fixes its option.
        dp: list[list[dict[str, Any] | None]] = [[] for _ in range(count)]
        best: list[dict[str, Any] | None] = [None for _ in range(count)]

        if fixed_first_option is None:
            dp[0] = []
            best[0] = None
            first_node: dict[str, Any] | None = None
        else:
            option = options[0][fixed_first_option]
            first_node = {
                "tooth": 0,
                "option": fixed_first_option,
                "score": option["own_score"],
                "parent": None,
            }
            dp[0] = [first_node]
            best[0] = first_node

        for tooth_index in range(1, count):
            states: list[dict[str, Any]] = []
            for option_index, option in enumerate(options[tooth_index]):
                parent: dict[str, Any] | None = None
                parent_score = 0.0

                # Leave the immediately preceding tooth position missing.
                # If tooth one was fixed, this route is unavailable at tooth 2.
                prefix_allowed = fixed_first_option is None or tooth_index >= 2
                if prefix_allowed:
                    prefix = best[tooth_index - 2] if tooth_index >= 2 else None
                    candidate_score = 0.0 if prefix is None else float(prefix["score"])
                    if candidate_score >= parent_score:
                        parent = prefix
                        parent_score = candidate_score

                # Or continue from an assignment at the preceding position.
                for previous in dp[tooth_index - 1]:
                    if previous is None:
                        continue
                    previous_option = options[tooth_index - 1][int(previous["option"])]
                    if previous_option["candidate_id"] == option["candidate_id"]:
                        continue
                    bonus = _gap_bonus(
                        option["unwrapped_angle"] - previous_option["unwrapped_angle"], pitch
                    )
                    if bonus is None:
                        continue
                    candidate_score = float(previous["score"]) + bonus
                    if candidate_score > parent_score or (
                        parent is not None and candidate_score == parent_score and bonus > 0
                    ):
                        parent = previous
                        parent_score = candidate_score

                if parent is None and not prefix_allowed:
                    continue
                states.append({
                    "tooth": tooth_index,
                    "option": option_index,
                    "score": option["own_score"] + parent_score,
                    "parent": parent,
                })

            dp[tooth_index] = states
            current_best = best[tooth_index - 1]
            for state in states:
                if current_best is None or state["score"] > float(current_best["score"]):
                    current_best = state
            best[tooth_index] = current_best

        if fixed_first_option is None:
            node = best[count - 1]
            return node, float(node["score"]) if node is not None else -1.0

        assert first_node is not None
        first_option = options[0][fixed_first_option]
        first_id = first_option["candidate_id"]
        first_close = first_option["unwrapped_angle"] + 360.0

        # Position count is at least six.  If the final numbered position is
        # missing, the best prefix through count-2 already handles closure.
        final_without_last = best[count - 2] if count >= 2 else first_node
        result_node = final_without_last
        result_total = float(final_without_last["score"]) if final_without_last else -1.0

        for node in dp[count - 1]:
            if node is None:
                continue
            option = options[count - 1][int(node["option"])]
            if option["candidate_id"] == first_id:
                continue
            closure_bonus = _gap_bonus(first_close - option["unwrapped_angle"], pitch)
            if closure_bonus is None:
                continue
            total = float(node["score"]) + closure_bonus
            if total > result_total:
                result_total = total
                result_node = node

        return result_node, result_total

    winning_node: dict[str, Any] | None = None
    winning_score = -1.0

    missing_first_node, missing_score = run_case(None)
    if missing_first_node is not None:
        winning_node = missing_first_node
        winning_score = missing_score

    for first_index in range(len(options[0])):
        node, total_score = run_case(first_index)
        if node is not None and total_score > winning_score:
            winning_node = node
            winning_score = total_score

    chosen: dict[int, int] = {}
    node = winning_node
    while node is not None:
        chosen[int(node["tooth"])] = int(node["option"])
        node = node.get("parent")

    teeth: list[dict[str, Any]] = []
    for tooth_index in range(count):
        nominal_angle = nominal[tooth_index]
        row: dict[str, Any] = {
            "index": tooth_index + 1,
            "tooth": tooth_index + 1,
            "number": tooth_index + 1,
            "tooth_number": tooth_index + 1,
            "label": f"第 {tooth_index + 1} 齿",
            "nominal_angle": nominal_angle,
            "status": "missing",
            "match_status": "missing",
            "assignment_status": "unassigned",
            "state": "missing",
            "evidence_status": "missing",
            "matched": False,
            "assigned": False,
            "has_evidence": False,
            "evidence": None,
            "source": None,
            "angle": None,
            "source_angle": None,
            "radius": None,
            "x": None,
            "y": None,
            "angular_error_deg": None,
            "score": None,
        }

        option_index = chosen.get(tooth_index)
        if option_index is not None:
            option = options[tooth_index][option_index]
            candidate = option["candidate"]
            source_angle = float(candidate.get("source_angle", candidate["angle"])) % 360.0
            evidence = {
                "angle": source_angle,
                "source_angle": source_angle,
                "ray_angle": candidate.get("ray_angle", candidate["angle"]),
                "x": candidate.get("x"),
                "y": candidate.get("y"),
                "radius": candidate.get("radius"),
                "clarity": candidate.get("clarity"),
                "strength": candidate.get("strength"),
                "fallback_left_px": candidate.get("fallback_left_px"),
                "fallback_right_px": candidate.get("fallback_right_px"),
            }
            row.update({
                "status": "seen",
                "match_status": "matched",
                "assignment_status": "assigned",
                "state": "seen",
                "evidence_status": "seen",
                "matched": True,
                "assigned": True,
                "has_evidence": True,
                "evidence": evidence,
                "source": dict(evidence),
                "angle": source_angle,
                "source_angle": source_angle,
                "radius": candidate.get("radius"),
                "x": candidate.get("x"),
                "y": candidate.get("y"),
                "angular_error_deg": round(float(option["angular_error"]), 6),
                "score": round(float(option["own_score"]), 6),
            })
        teeth.append(row)

    return teeth


def tooth_at_angle(teeth: list[dict[str, Any]], anchor_angle: float | None, angle: float) -> dict[str, Any] | None:
    if not teeth or anchor_angle is None:
        return None
    count = len(teeth)
    pitch = 360.0 / count
    clockwise = (norm_angle(angle) - norm_angle(anchor_angle)) % 360.0
    index = int(math.floor(clockwise / pitch + 0.5)) % count
    return teeth[index]


def layout_report(
    count: int,
    anchor_angle: float | None,
    candidates: list[dict[str, Any]],
    current_angle: float | None = None,
) -> dict[str, Any]:
    adopted = anchor_angle is not None
    teeth = assign_teeth(count, anchor_angle, candidates) if adopted else []
    current = tooth_at_angle(teeth, anchor_angle, current_angle) if adopted and current_angle is not None else None
    seen = sum(1 for row in teeth if row["has_evidence"])
    return {
        "adopted": adopted,
        "anchor_angle": norm_angle(anchor_angle) if anchor_angle is not None else None,
        "first_tooth_angle": norm_angle(anchor_angle) if anchor_angle is not None else None,
        "pitch_deg": 360.0 / int(count),
        "angle_tolerance_deg": 0.6 * 360.0 / int(count),
        "teeth": teeth,
        "assignments": teeth,
        "positions": teeth,
        "tooth_positions": teeth,
        "mapping": teeth,
        "seen_count": seen,
        "matched_count": seen,
        "evidence_count": seen,
        "missing_count": len(teeth) - seen,
        "current_tooth": current,
    }


assign_positions = assign_teeth
build_layout = layout_report
