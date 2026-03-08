from .metrics import is_finite_number


PRIMARY_LABEL_ORDER = [
    "invalid_candidate",
    "behaviorally_duplicate",
    "high_symmetry_collapse_risk",
    "narrow_generalization",
    "fragmentation_prone",
    "aggressive_opening",
    "low_confidence_policy",
    "robust_but_conservative",
]


def _invalid_labels(runtime_error, error_type):
    labels = ["invalid_candidate"]
    error_text = f"{error_type or ''} {runtime_error or ''}".lower()
    if "indentation" in error_text or "syntax" in error_text:
        labels.append("syntax_invalid")
    elif "timeout" in error_text:
        labels.append("timeout_invalid")
    else:
        labels.append("evaluation_invalid")
    return labels


def assign_diagnosis(card, thresholds, generation_context=None):
    generation_context = generation_context or {}

    if not card["identity"]["valid"]:
        labels = _invalid_labels(
            card["performance"].get("runtime_error"),
            card["diagnosis"].get("error_type"),
        )
        return {
            "labels": labels,
            "primary_label": "invalid_candidate",
            "confidence": 1.0,
            "evidence": {
                "runtime_error": card["performance"].get("runtime_error"),
            },
            "error_type": card["diagnosis"].get("error_type"),
        }

    behavior = card["behavior"]
    robustness = card["robustness"]
    duplicates = card["duplicates"]
    evidence = {}
    labels = []

    if duplicates.get("is_behavior_duplicate"):
        labels.append("behaviorally_duplicate")
        evidence["behavior_duplicate_group_id"] = duplicates.get("behavior_duplicate_group_id")

    if (
        is_finite_number(behavior.get("duplicate_capacity_rate"))
        and behavior["duplicate_capacity_rate"] >= thresholds["high_symmetry_duplicate_capacity_rate"]
        and is_finite_number(behavior.get("tie_hit_rate"))
        and behavior["tie_hit_rate"] >= thresholds["high_symmetry_tie_hit_rate"]
        and is_finite_number(behavior.get("mean_chosen_capacity_group_size"))
        and behavior["mean_chosen_capacity_group_size"] >= thresholds["high_symmetry_chosen_group_size"]
    ):
        labels.append("high_symmetry_collapse_risk")
        evidence["duplicate_capacity_rate"] = behavior.get("duplicate_capacity_rate")
        evidence["tie_hit_rate"] = behavior.get("tie_hit_rate")
        evidence["mean_chosen_capacity_group_size"] = behavior.get("mean_chosen_capacity_group_size")

    if (
        is_finite_number(behavior.get("top1_top2_margin_mean"))
        and behavior["top1_top2_margin_mean"] <= thresholds["low_confidence_margin_mean"]
    ):
        labels.append("low_confidence_policy")
        evidence["top1_top2_margin_mean"] = behavior.get("top1_top2_margin_mean")

    if (
        is_finite_number(behavior.get("bin_opening_ratio_first_third"))
        and behavior["bin_opening_ratio_first_third"] >= thresholds["aggressive_opening_ratio_first_third"]
    ):
        labels.append("aggressive_opening")
        evidence["bin_opening_ratio_first_third"] = behavior.get("bin_opening_ratio_first_third")

    if (
        is_finite_number(behavior.get("var_leftover_after_placement"))
        and behavior["var_leftover_after_placement"] >= thresholds["fragmentation_var_leftover"]
        and is_finite_number(behavior.get("mean_leftover_after_placement"))
        and thresholds["fragmentation_mean_leftover_low"] <= behavior["mean_leftover_after_placement"] <= thresholds["fragmentation_mean_leftover_high"]
    ):
        labels.append("fragmentation_prone")
        evidence["var_leftover_after_placement"] = behavior.get("var_leftover_after_placement")
        evidence["mean_leftover_after_placement"] = behavior.get("mean_leftover_after_placement")

    if (
        is_finite_number(robustness.get("permuted_order_score_drop"))
        and robustness["permuted_order_score_drop"] <= thresholds["robustness_score_drop"]
        and is_finite_number(robustness.get("instance_variance_bins_used"))
        and robustness["instance_variance_bins_used"] <= thresholds["low_instance_variance_bins_used"]
        and (duplicates.get("is_behavior_duplicate") or "high_symmetry_collapse_risk" in labels)
    ):
        labels.append("robust_but_conservative")
        evidence["permuted_order_score_drop"] = robustness.get("permuted_order_score_drop")
        evidence["instance_variance_bins_used"] = robustness.get("instance_variance_bins_used")

    generation_objectives = generation_context.get("valid_objectives") or []
    objective = card["identity"].get("objective")
    median_objective = None
    if generation_objectives:
        ordered = sorted(generation_objectives)
        median_objective = ordered[len(ordered) // 2]

    if (
        is_finite_number(objective)
        and median_objective is not None
        and objective <= median_objective
        and (
            (
                is_finite_number(robustness.get("permuted_order_score_drop"))
                and robustness["permuted_order_score_drop"] >= thresholds["narrow_generalization_score_drop"]
            )
            or (
                is_finite_number(robustness.get("instance_variance_bins_used"))
                and robustness["instance_variance_bins_used"] >= thresholds["high_instance_variance_bins_used"]
            )
        )
    ):
        labels.append("narrow_generalization")
        evidence["median_generation_objective"] = median_objective
        evidence["permuted_order_score_drop"] = robustness.get("permuted_order_score_drop")
        evidence["instance_variance_bins_used"] = robustness.get("instance_variance_bins_used")

    primary_label = None
    for label in PRIMARY_LABEL_ORDER:
        if label in labels:
            primary_label = label
            break
    if primary_label is None:
        primary_label = "unlabeled"

    confidence = 0.5
    if primary_label == "behaviorally_duplicate":
        confidence = 0.95
    elif primary_label == "high_symmetry_collapse_risk":
        confidence = 0.9
    elif labels:
        confidence = 0.75

    return {
        "labels": labels,
        "primary_label": primary_label,
        "confidence": confidence,
        "evidence": evidence,
        "error_type": None,
    }
