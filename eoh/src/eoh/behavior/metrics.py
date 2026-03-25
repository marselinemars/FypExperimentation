import ast
import math
import re

from .tsp_metrics import compute_tsp_behavior_metrics


def _safe_len_lines(code_string):
    if not code_string:
        return None
    return len(code_string.splitlines())


def _null_structure():
    return {
        "code_length_chars": None,
        "code_length_lines": None,
        "num_numeric_constants": None,
        "num_conditionals": None,
        "num_arithmetic_ops": None,
        "uses_sorting": None,
        "uses_loops": None,
        "ast_depth_estimate": None,
        "summary": "unavailable",
    }


def compute_structure_metrics(code_string, algorithm_summary=None):
    metrics = _null_structure()
    metrics["summary"] = (algorithm_summary or "unavailable")[:280]
    if not code_string:
        return metrics

    metrics["code_length_chars"] = len(code_string)
    metrics["code_length_lines"] = _safe_len_lines(code_string)
    metrics["uses_sorting"] = bool(re.search(r"\b(sorted|sort|argsort)\b", code_string))
    metrics["uses_loops"] = bool(re.search(r"\b(for|while)\b", code_string))

    try:
        tree = ast.parse(code_string)
    except SyntaxError:
        return metrics

    metrics["num_numeric_constants"] = 0
    metrics["num_conditionals"] = 0
    metrics["num_arithmetic_ops"] = 0

    arithmetic_nodes = (
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
    )

    def walk_depth(node, depth=1):
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            max_depth = max(max_depth, walk_depth(child, depth + 1))
        return max_depth

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            metrics["num_numeric_constants"] += 1
        elif isinstance(node, ast.Num):
            metrics["num_numeric_constants"] += 1
        if isinstance(node, (ast.If, ast.IfExp)):
            metrics["num_conditionals"] += 1
        if isinstance(node, ast.BinOp) and isinstance(node.op, arithmetic_nodes):
            metrics["num_arithmetic_ops"] += 1
        if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            metrics["uses_loops"] = True

    metrics["ast_depth_estimate"] = walk_depth(tree)
    return metrics


def null_behavior_metrics():
    return {
        "choice_trace_signature": None,
        "raw_next_node_trace_signature": None,
        "rank_trace_signature": None,
        "score_trace_signature": None,
        "trace_length": None,
        "unique_bins_chosen": None,
        "decision_entropy": None,
        "top1_top2_margin_mean": None,
        "top1_top2_margin_std": None,
        "tie_hit_rate": None,
        "duplicate_capacity_rate": None,
        "mean_chosen_capacity_group_size": None,
        "bin_opening_ratio_first_third": None,
        "mean_leftover_after_placement": None,
        "var_leftover_after_placement": None,
        "near_full_placement_ratio": None,
        "near_empty_placement_ratio": None,
        "mean_chosen_rank": None,
        "mean_chosen_rank_ratio": None,
        "nearest_neighbor_pick_rate": None,
        "top3_pick_rate": None,
        "long_jump_rate": None,
        "mean_selected_edge_length": None,
        "var_selected_edge_length": None,
        "mean_selected_distance_percentile": None,
        "rank_bucket_entropy": None,
        "early_vs_late_rank_shift": None,
        "instance_rank_ratio_std": None,
        "traced_instance_ids": [],
    }


def _compute_bp_online_behavior_metrics(traces):
    metrics = null_behavior_metrics()
    if not traces:
        return metrics

    trace_records = list(traces.values())
    first = trace_records[0]
    step_metrics = first.get("decision_metrics") or {}
    metrics.update(
        {
            "choice_trace_signature": first.get("choice_trace_signature"),
            "score_trace_signature": first.get("score_trace_signature"),
            "trace_length": step_metrics.get("trace_length"),
            "unique_bins_chosen": step_metrics.get("unique_bins_chosen"),
            "decision_entropy": step_metrics.get("decision_entropy"),
            "top1_top2_margin_mean": step_metrics.get("top1_top2_margin_mean"),
            "top1_top2_margin_std": step_metrics.get("top1_top2_margin_std"),
            "tie_hit_rate": step_metrics.get("tie_hit_rate"),
            "duplicate_capacity_rate": step_metrics.get("duplicate_capacity_rate"),
            "mean_chosen_capacity_group_size": step_metrics.get("mean_chosen_capacity_group_size"),
            "bin_opening_ratio_first_third": step_metrics.get("bin_opening_ratio_first_third"),
            "mean_leftover_after_placement": step_metrics.get("mean_leftover_after_placement"),
            "var_leftover_after_placement": step_metrics.get("var_leftover_after_placement"),
            "near_full_placement_ratio": step_metrics.get("near_full_placement_ratio"),
            "near_empty_placement_ratio": step_metrics.get("near_empty_placement_ratio"),
            "traced_instance_ids": sorted(traces.keys()),
        }
    )
    return metrics


def compute_behavior_metrics(problem_type, traces):
    if problem_type == "tsp_construct":
        return compute_tsp_behavior_metrics(traces, null_behavior_metrics())
    return _compute_bp_online_behavior_metrics(traces)


def null_robustness_metrics():
    return {
        "permuted_order_score_drop": None,
        "permuted_order_trace_change_rate": None,
        "instance_variance_bins_used": None,
        "instance_variance_score": None,
        "alt_start_relative_score_delta": None,
        "alt_start_trace_change_rate": None,
        "instance_variance_tour_length": None,
        "instance_cv_tour_length": None,
    }


def compute_robustness_metrics(problem_type, payload):
    metrics = null_robustness_metrics()
    if not payload:
        return metrics
    metrics.update(payload)
    return metrics


def is_finite_number(value):
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))
