from .metrics import is_finite_number


TSP_PRIMARY_LABEL_ORDER = [
    "invalid_candidate",
    "behaviorally_duplicate",
    "unstable_start_sensitive",
    "narrow_generalization",
    "repetitive_ranking_pattern",
    "overly_greedy_local_policy",
    "exploration_heavy_policy",
    "robust_but_conservative",
    "edge_length_extreme_bias",
]


def assign_tsp_diagnosis(card, thresholds, generation_context=None):
    generation_context = generation_context or {}

    behavior = card["behavior"]
    robustness = card["robustness"]
    duplicates = card["duplicates"]
    evidence = {}
    labels = []

    if duplicates.get("is_behavior_duplicate"):
        labels.append("behaviorally_duplicate")
        evidence["behavior_duplicate_group_id"] = duplicates.get("behavior_duplicate_group_id")

    if (
        is_finite_number(behavior.get("nearest_neighbor_pick_rate"))
        and behavior["nearest_neighbor_pick_rate"] >= thresholds["greedy_local_nearest_neighbor_rate"]
        and is_finite_number(behavior.get("mean_chosen_rank_ratio"))
        and behavior["mean_chosen_rank_ratio"] <= thresholds["greedy_local_mean_rank_ratio"]
    ):
        labels.append("overly_greedy_local_policy")
        evidence["nearest_neighbor_pick_rate"] = behavior.get("nearest_neighbor_pick_rate")
        evidence["mean_chosen_rank_ratio"] = behavior.get("mean_chosen_rank_ratio")

    if (
        is_finite_number(behavior.get("long_jump_rate"))
        and behavior["long_jump_rate"] >= thresholds["exploration_long_jump_rate"]
        and is_finite_number(behavior.get("mean_chosen_rank_ratio"))
        and behavior["mean_chosen_rank_ratio"] >= thresholds["exploration_mean_rank_ratio"]
    ):
        labels.append("exploration_heavy_policy")
        evidence["long_jump_rate"] = behavior.get("long_jump_rate")
        evidence["mean_chosen_rank_ratio"] = behavior.get("mean_chosen_rank_ratio")

    if (
        is_finite_number(behavior.get("rank_bucket_entropy"))
        and behavior["rank_bucket_entropy"] <= thresholds["repetitive_rank_bucket_entropy"]
        and (
            (
                is_finite_number(behavior.get("top3_pick_rate"))
                and behavior["top3_pick_rate"] >= thresholds["repetitive_top3_rate"]
            )
            or (
                is_finite_number(behavior.get("long_jump_rate"))
                and behavior["long_jump_rate"] >= thresholds["repetitive_long_jump_rate"]
            )
        )
    ):
        labels.append("repetitive_ranking_pattern")
        evidence["rank_bucket_entropy"] = behavior.get("rank_bucket_entropy")
        evidence["top3_pick_rate"] = behavior.get("top3_pick_rate")
        evidence["long_jump_rate"] = behavior.get("long_jump_rate")

    if (
        (
            is_finite_number(robustness.get("alt_start_relative_score_delta"))
            and robustness["alt_start_relative_score_delta"] >= thresholds["unstable_alt_start_score_delta"]
        )
        or (
            is_finite_number(robustness.get("alt_start_trace_change_rate"))
            and robustness["alt_start_trace_change_rate"] >= thresholds["unstable_alt_start_trace_change_rate"]
        )
    ):
        labels.append("unstable_start_sensitive")
        evidence["alt_start_relative_score_delta"] = robustness.get("alt_start_relative_score_delta")
        evidence["alt_start_trace_change_rate"] = robustness.get("alt_start_trace_change_rate")

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
                is_finite_number(robustness.get("instance_cv_tour_length"))
                and robustness["instance_cv_tour_length"] >= thresholds["narrow_generalization_instance_cv"]
            )
            or (
                is_finite_number(robustness.get("alt_start_relative_score_delta"))
                and robustness["alt_start_relative_score_delta"] >= thresholds["unstable_alt_start_score_delta"]
            )
        )
    ):
        labels.append("narrow_generalization")
        evidence["median_generation_objective"] = median_objective
        evidence["instance_cv_tour_length"] = robustness.get("instance_cv_tour_length")
        evidence["alt_start_relative_score_delta"] = robustness.get("alt_start_relative_score_delta")

    if (
        is_finite_number(robustness.get("alt_start_relative_score_delta"))
        and robustness["alt_start_relative_score_delta"] <= thresholds["robust_alt_start_score_delta"]
        and is_finite_number(robustness.get("instance_cv_tour_length"))
        and robustness["instance_cv_tour_length"] <= thresholds["robust_instance_cv"]
        and ("behaviorally_duplicate" in labels or "overly_greedy_local_policy" in labels)
    ):
        labels.append("robust_but_conservative")
        evidence["alt_start_relative_score_delta"] = robustness.get("alt_start_relative_score_delta")
        evidence["instance_cv_tour_length"] = robustness.get("instance_cv_tour_length")

    if (
        is_finite_number(behavior.get("mean_selected_distance_percentile"))
        and (
            behavior["mean_selected_distance_percentile"] <= thresholds["extreme_distance_percentile_low"]
            or behavior["mean_selected_distance_percentile"] >= thresholds["extreme_distance_percentile_high"]
        )
    ):
        labels.append("edge_length_extreme_bias")
        evidence["mean_selected_distance_percentile"] = behavior.get("mean_selected_distance_percentile")

    primary_label = None
    for label in TSP_PRIMARY_LABEL_ORDER:
        if label in labels:
            primary_label = label
            break
    if primary_label is None:
        primary_label = "unlabeled"

    confidence = 0.5
    if primary_label == "behaviorally_duplicate":
        confidence = 0.95
    elif primary_label in ["unstable_start_sensitive", "narrow_generalization"]:
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
