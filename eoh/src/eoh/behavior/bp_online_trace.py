import hashlib
import json
import math
import re
import types

import numpy as np

from ..methods.eoh.evaluator_accelerate import add_numba_decorator


def sha256_json(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_evaluation_code(code_string, use_numba):
    if not code_string:
        return None
    if not use_numba:
        return code_string
    match = re.search(r"def\s+(\w+)\s*\(.*\):", code_string)
    if match is None:
        raise ValueError("unable to identify function name for numba decoration")
    return add_numba_decorator(program=code_string, function_name=match.group(1))


def load_algorithm_module(code_string):
    module = types.ModuleType("behavior_trace_module")
    exec(code_string, module.__dict__)
    return module


def _float_or_none(value):
    try:
        value = float(value)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return value


def _safe_priority_vector(priorities):
    array = np.asarray(priorities)
    if array.ndim != 1:
        raise ValueError("score() must return a 1D priority vector")
    return array


def _top_score_metrics(priorities, tie_score_epsilon):
    if len(priorities) == 0:
        return {
            "top1_score": None,
            "top2_score": None,
            "top1_top2_margin": None,
            "top_score_tie_count": 0,
        }
    sorted_indices = np.argsort(priorities)
    top1 = _float_or_none(priorities[sorted_indices[-1]])
    top2 = _float_or_none(priorities[sorted_indices[-2]]) if len(priorities) > 1 else None
    margin = (top1 - top2) if top1 is not None and top2 is not None else None

    tie_count = 0
    if top1 is not None:
        for value in priorities:
            value = _float_or_none(value)
            if value is not None and abs(value - top1) <= tie_score_epsilon:
                tie_count += 1

    return {
        "top1_score": top1,
        "top2_score": top2,
        "top1_top2_margin": margin,
        "top_score_tie_count": int(tie_count),
    }


def _make_rng(permutation_seed, instance_id):
    derived = permutation_seed + sum(ord(ch) for ch in str(instance_id))
    return np.random.default_rng(derived)


def _decision_entropy(chosen_bins):
    if not chosen_bins:
        return 0.0
    _, counts = np.unique(np.array(chosen_bins), return_counts=True)
    probs = counts / counts.sum()
    return -float(np.sum(probs * np.log2(probs)))


def _instance_l1_bound(items, capacity):
    return float(np.ceil(np.sum(items) / capacity))


def _replay_instance(problem, alg, instance, trace_prefix_steps, tie_score_epsilon, near_full_ratio, near_empty_ratio):
    capacity = instance["capacity"]
    items = np.array(instance["items"])
    bins = np.array([capacity for _ in range(instance["num_items"])], dtype=np.float64)

    traced_steps = []
    all_chosen_bins = []
    all_margins = []
    all_leftovers = []
    duplicate_capacity_hits = 0
    tie_hits = 0
    chosen_capacity_group_sizes = []
    opening_events = []
    near_full_hits = 0
    near_empty_hits = 0

    for step_index, item in enumerate(items):
        valid_bin_indices = problem.get_valid_bin_indices(item, bins)
        valid_bins = bins[valid_bin_indices]
        unique_capacities, counts = np.unique(valid_bins, return_counts=True)
        duplicate_capacity_count = int(len(valid_bin_indices) - len(unique_capacities))
        if duplicate_capacity_count > 0:
            duplicate_capacity_hits += 1

        priorities = _safe_priority_vector(alg.score(item, valid_bins))
        if len(priorities) != len(valid_bin_indices):
            raise ValueError("score() output length does not match feasible bin count")

        best_local_index = int(np.argmax(priorities))
        best_bin = int(valid_bin_indices[best_local_index])
        chosen_capacity = float(bins[best_bin])
        chosen_capacity_group_size = int(counts[unique_capacities == chosen_capacity][0])
        chosen_capacity_group_sizes.append(chosen_capacity_group_size)

        score_metrics = _top_score_metrics(priorities, tie_score_epsilon)
        if score_metrics["top1_top2_margin"] is not None:
            all_margins.append(score_metrics["top1_top2_margin"])
        if score_metrics["top_score_tie_count"] > 1:
            tie_hits += 1

        pre_remaining = float(bins[best_bin])
        bins[best_bin] -= item
        post_remaining = float(bins[best_bin])

        all_chosen_bins.append(best_bin)
        all_leftovers.append(post_remaining)
        opening_events.append(1 if abs(pre_remaining - capacity) <= tie_score_epsilon else 0)
        if post_remaining <= near_full_ratio * capacity:
            near_full_hits += 1
        if post_remaining >= near_empty_ratio * capacity:
            near_empty_hits += 1

        if step_index < trace_prefix_steps:
            traced_steps.append(
                {
                    "step_index": int(step_index),
                    "item": int(item),
                    "valid_bin_count": int(len(valid_bin_indices)),
                    "unique_capacity_count": int(len(unique_capacities)),
                    "duplicate_capacity_count": duplicate_capacity_count,
                    "max_equal_capacity_group_size": int(np.max(counts)),
                    "chosen_capacity_group_size": chosen_capacity_group_size,
                    "chosen_bin_index": best_bin,
                    "priority_argmax_index": best_local_index,
                    "top1_score": score_metrics["top1_score"],
                    "top2_score": score_metrics["top2_score"],
                    "top1_top2_margin": score_metrics["top1_top2_margin"],
                    "top_score_tie_count": score_metrics["top_score_tie_count"],
                    "pre_remaining_capacity": pre_remaining,
                    "post_remaining_capacity": post_remaining,
                }
            )

    used_bins = int((bins != capacity).sum())
    instance_lb = _instance_l1_bound(items, capacity)
    instance_score = float((used_bins - instance_lb) / instance_lb)

    return {
        "capacity": int(capacity),
        "used_bins": used_bins,
        "instance_lower_bound": instance_lb,
        "instance_score": instance_score,
        "full_step_count": int(len(items)),
        "trace_steps": traced_steps,
        "choice_trace_signature": sha256_json(
            [
                {
                    "step_index": step["step_index"],
                    "item": step["item"],
                    "chosen_bin_index": step["chosen_bin_index"],
                    "priority_argmax_index": step["priority_argmax_index"],
                }
                for step in traced_steps
            ]
        ),
        "score_trace_signature": sha256_json(
            [
                {
                    "step_index": step["step_index"],
                    "top1_score": step["top1_score"],
                    "top2_score": step["top2_score"],
                    "top1_top2_margin": step["top1_top2_margin"],
                    "top_score_tie_count": step["top_score_tie_count"],
                    "chosen_capacity_group_size": step["chosen_capacity_group_size"],
                }
                for step in traced_steps
            ]
        ),
        "decision_metrics": {
            "trace_length": len(traced_steps),
            "unique_bins_chosen": int(len(set(all_chosen_bins))),
            "decision_entropy": float(_decision_entropy(all_chosen_bins)),
            "top1_top2_margin_mean": _float_or_none(np.mean(all_margins)) if all_margins else None,
            "top1_top2_margin_std": _float_or_none(np.std(all_margins)) if all_margins else None,
            "tie_hit_rate": float(tie_hits / len(items)) if len(items) else None,
            "duplicate_capacity_rate": float(duplicate_capacity_hits / len(items)) if len(items) else None,
            "mean_chosen_capacity_group_size": float(np.mean(chosen_capacity_group_sizes)) if chosen_capacity_group_sizes else None,
            "bin_opening_ratio_first_third": float(np.mean(opening_events[: max(1, len(opening_events) // 3)])) if opening_events else None,
            "mean_leftover_after_placement": _float_or_none(np.mean(all_leftovers)) if all_leftovers else None,
            "var_leftover_after_placement": _float_or_none(np.var(all_leftovers)) if all_leftovers else None,
            "near_full_placement_ratio": float(near_full_hits / len(items)) if len(items) else None,
            "near_empty_placement_ratio": float(near_empty_hits / len(items)) if len(items) else None,
        },
    }


class BPOnlineTraceExtractor:
    def __init__(self, problem, trace_config):
        self.problem = problem
        self.trace_config = trace_config

    def evaluate_candidate(self, code_string, use_numba):
        evaluation_code = build_evaluation_code(code_string, use_numba)
        alg = load_algorithm_module(evaluation_code)

        traced_instance_ids = set(self.trace_config.get("traced_instance_ids") or [])
        trace_prefix_steps = int(self.trace_config.get("trace_prefix_steps", 200))
        permutation_seed = int(self.trace_config.get("permutation_seed", 2024))
        tie_score_epsilon = float(self.trace_config.get("tie_score_epsilon", 1e-12))
        near_full_ratio = float(self.trace_config.get("near_full_leftover_ratio", 0.1))
        near_empty_ratio = float(self.trace_config.get("near_empty_leftover_ratio", 0.8))

        full_search_bins_used = {}
        full_search_scores = {}
        traced_instances = {}
        group_metrics = []

        for problem_name, dataset in self.problem.instances.items():
            used_bins_values = []
            for instance_id, instance in dataset.items():
                replay = _replay_instance(
                    self.problem,
                    alg,
                    instance,
                    trace_prefix_steps=trace_prefix_steps if instance_id in traced_instance_ids else 0,
                    tie_score_epsilon=tie_score_epsilon,
                    near_full_ratio=near_full_ratio,
                    near_empty_ratio=near_empty_ratio,
                )
                full_search_bins_used[instance_id] = replay["used_bins"]
                full_search_scores[instance_id] = replay["instance_score"]
                used_bins_values.append(replay["used_bins"])
                if instance_id in traced_instance_ids:
                    traced_instances[instance_id] = replay

            avg_num_bins = float(np.mean(used_bins_values))
            lower_bound = float(self.problem.lb[problem_name])
            fitness = float((avg_num_bins - lower_bound) / lower_bound)
            group_metrics.append(
                {
                    "problem_name": problem_name,
                    "avg_num_bins": avg_num_bins,
                    "lower_bound": lower_bound,
                    "fitness": fitness,
                }
            )

        permuted = self._evaluate_permuted_orders(alg, traced_instance_ids, permutation_seed)

        return {
            "evaluation_code": evaluation_code,
            "full_search_metrics": {
                "per_instance_bins_used": full_search_bins_used,
                "per_instance_scores": full_search_scores,
                "valid_instance_count": len(full_search_bins_used),
                "search_problem_metrics": group_metrics,
            },
            "traced_instance_metrics": {
                "instance_ids": sorted(traced_instances.keys()),
                "per_instance_bins_used": {key: value["used_bins"] for key, value in traced_instances.items()},
                "per_instance_scores": {key: value["instance_score"] for key, value in traced_instances.items()},
            },
            "traces": traced_instances,
            "robustness": permuted,
        }

    def _evaluate_permuted_orders(self, alg, traced_instance_ids, permutation_seed):
        if not traced_instance_ids:
            return {
                "permuted_order_score_drop": None,
                "permuted_order_trace_change_rate": None,
                "instance_variance_bins_used": None,
                "instance_variance_score": None,
            }

        original_scores = []
        permuted_scores = []
        trace_change_rates = []
        traced_bins = []

        for dataset in self.problem.instances.values():
            for instance_id, instance in dataset.items():
                if instance_id not in traced_instance_ids:
                    continue

                original = _replay_instance(
                    self.problem,
                    alg,
                    instance,
                    trace_prefix_steps=int(self.trace_config.get("trace_prefix_steps", 200)),
                    tie_score_epsilon=float(self.trace_config.get("tie_score_epsilon", 1e-12)),
                    near_full_ratio=float(self.trace_config.get("near_full_leftover_ratio", 0.1)),
                    near_empty_ratio=float(self.trace_config.get("near_empty_leftover_ratio", 0.8)),
                )
                traced_bins.append(original["used_bins"])
                original_scores.append(original["instance_score"])

                rng = _make_rng(permutation_seed, instance_id)
                permuted_items = np.array(instance["items"])[rng.permutation(instance["num_items"])]
                permuted_instance = dict(instance)
                permuted_instance["items"] = permuted_items.tolist()
                permuted = _replay_instance(
                    self.problem,
                    alg,
                    permuted_instance,
                    trace_prefix_steps=int(self.trace_config.get("trace_prefix_steps", 200)),
                    tie_score_epsilon=float(self.trace_config.get("tie_score_epsilon", 1e-12)),
                    near_full_ratio=float(self.trace_config.get("near_full_leftover_ratio", 0.1)),
                    near_empty_ratio=float(self.trace_config.get("near_empty_leftover_ratio", 0.8)),
                )
                permuted_scores.append(permuted["instance_score"])

                original_choices = [step["chosen_bin_index"] for step in original["trace_steps"]]
                permuted_choices = [step["chosen_bin_index"] for step in permuted["trace_steps"]]
                compared = min(len(original_choices), len(permuted_choices))
                if compared == 0:
                    trace_change_rates.append(None)
                else:
                    changed = sum(
                        1
                        for index in range(compared)
                        if original_choices[index] != permuted_choices[index]
                    )
                    trace_change_rates.append(changed / compared)

        valid_change_rates = [value for value in trace_change_rates if value is not None]
        return {
            "permuted_order_score_drop": _float_or_none(np.mean(permuted_scores) - np.mean(original_scores)) if original_scores and permuted_scores else None,
            "permuted_order_trace_change_rate": _float_or_none(np.mean(valid_change_rates)) if valid_change_rates else None,
            "instance_variance_bins_used": _float_or_none(np.var(traced_bins)) if traced_bins else None,
            "instance_variance_score": _float_or_none(np.var(original_scores)) if original_scores else None,
        }
