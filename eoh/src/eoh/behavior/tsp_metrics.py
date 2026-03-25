import hashlib
import json
import math

import numpy as np


def _safe_float(value):
    try:
        value = float(value)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return value


def _safe_mean(values):
    if not values:
        return None
    return _safe_float(np.mean(values))


def _safe_std(values):
    if not values:
        return None
    return _safe_float(np.std(values))


def _safe_var(values):
    if not values:
        return None
    return _safe_float(np.var(values))


def _sha256_json(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _entropy(values):
    if not values:
        return 0.0
    _, counts = np.unique(np.array(values), return_counts=True)
    probs = counts / counts.sum()
    return -float(np.sum(probs * np.log2(probs)))


def _rank_bucket(rank_ratio):
    if rank_ratio is None:
        return None
    if rank_ratio < 0.2:
        return 0
    if rank_ratio < 0.4:
        return 1
    if rank_ratio < 0.6:
        return 2
    if rank_ratio < 0.8:
        return 3
    return 4


def compute_tsp_behavior_metrics(traces, metrics_template):
    metrics = dict(metrics_template)
    if not traces:
        return metrics

    ordered_ids = sorted(traces.keys())
    all_steps = []
    per_instance_mean_rank = []

    raw_signature_payload = []
    rank_signature_payload = []

    for instance_id in ordered_ids:
        trace = traces[instance_id]
        steps = trace.get("trace_steps") or []
        all_steps.extend(steps)

        rank_ratios = [step.get("chosen_rank_ratio") for step in steps if step.get("chosen_rank_ratio") is not None]
        if rank_ratios:
            per_instance_mean_rank.append(float(np.mean(rank_ratios)))

        for step in steps:
            raw_signature_payload.append(
                {
                    "instance_id": instance_id,
                    "step_index": step.get("step_index"),
                    "current_node": step.get("current_node"),
                    "chosen_node": step.get("chosen_node"),
                }
            )
            rank_signature_payload.append(
                {
                    "instance_id": instance_id,
                    "step_index": step.get("step_index"),
                    "chosen_rank": step.get("chosen_rank"),
                    "chosen_rank_ratio": step.get("chosen_rank_ratio"),
                    "rank_bucket": _rank_bucket(step.get("chosen_rank_ratio")),
                }
            )

    chosen_ranks = [step.get("chosen_rank") for step in all_steps if step.get("chosen_rank") is not None]
    rank_ratios = [step.get("chosen_rank_ratio") for step in all_steps if step.get("chosen_rank_ratio") is not None]
    edge_lengths = [step.get("chosen_edge_length") for step in all_steps if step.get("chosen_edge_length") is not None]
    chosen_nodes = [step.get("chosen_node") for step in all_steps if step.get("chosen_node") is not None]
    rank_buckets = [_rank_bucket(value) for value in rank_ratios if value is not None]

    early_count = max(1, len(rank_ratios) // 3) if rank_ratios else 0
    early_mean = _safe_mean(rank_ratios[:early_count]) if early_count else None
    late_mean = _safe_mean(rank_ratios[-early_count:]) if early_count else None
    early_vs_late_rank_shift = None
    if early_mean is not None and late_mean is not None:
        early_vs_late_rank_shift = _safe_float(late_mean - early_mean)

    metrics.update(
        {
            "choice_trace_signature": _sha256_json(rank_signature_payload),
            "raw_next_node_trace_signature": _sha256_json(raw_signature_payload),
            "rank_trace_signature": _sha256_json(rank_signature_payload),
            "score_trace_signature": None,
            "trace_length": len(all_steps),
            "unique_bins_chosen": len(set(chosen_nodes)) if chosen_nodes else None,
            "decision_entropy": _safe_float(_entropy(rank_buckets)) if rank_buckets else None,
            "top1_top2_margin_mean": None,
            "top1_top2_margin_std": None,
            "tie_hit_rate": _safe_mean(
                [1.0 if (step.get("chosen_distance_group_size") or 0) > 1 else 0.0 for step in all_steps]
            ),
            "duplicate_capacity_rate": _safe_mean(
                [1.0 if (step.get("duplicate_distance_count") or 0) > 0 else 0.0 for step in all_steps]
            ),
            "mean_chosen_capacity_group_size": _safe_mean(
                [step.get("chosen_distance_group_size") for step in all_steps if step.get("chosen_distance_group_size") is not None]
            ),
            "bin_opening_ratio_first_third": None,
            "mean_leftover_after_placement": None,
            "var_leftover_after_placement": None,
            "near_full_placement_ratio": None,
            "near_empty_placement_ratio": None,
            "mean_chosen_rank": _safe_mean(chosen_ranks),
            "mean_chosen_rank_ratio": _safe_mean(rank_ratios),
            "nearest_neighbor_pick_rate": _safe_mean([1.0 if value == 0 else 0.0 for value in chosen_ranks]),
            "top3_pick_rate": _safe_mean([1.0 if value <= 2 else 0.0 for value in chosen_ranks]),
            "long_jump_rate": _safe_mean([1.0 if value >= 0.8 else 0.0 for value in rank_ratios]),
            "mean_selected_edge_length": _safe_mean(edge_lengths),
            "var_selected_edge_length": _safe_var(edge_lengths),
            "mean_selected_distance_percentile": _safe_mean(rank_ratios),
            "rank_bucket_entropy": _safe_float(_entropy(rank_buckets)) if rank_buckets else None,
            "early_vs_late_rank_shift": early_vs_late_rank_shift,
            "instance_rank_ratio_std": _safe_std(per_instance_mean_rank),
            "traced_instance_ids": ordered_ids,
        }
    )
    return metrics
