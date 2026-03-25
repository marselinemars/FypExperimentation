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
    module = types.ModuleType("behavior_trace_module_tsp")
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


def _decision_entropy(choices):
    if not choices:
        return 0.0
    _, counts = np.unique(np.array(choices), return_counts=True)
    probs = counts / counts.sum()
    return -float(np.sum(probs * np.log2(probs)))


def _tour_cost(instance, solution, problem_size):
    cost = 0.0
    for j in range(problem_size - 1):
        cost += np.linalg.norm(instance[int(solution[j])] - instance[int(solution[j + 1])])
    cost += np.linalg.norm(instance[int(solution[-1])] - instance[int(solution[0])])
    return float(cost)


def _generate_neighborhood_matrix(instance):
    instance = np.array(instance)
    n = len(instance)
    neighborhood_matrix = np.zeros((n, n), dtype=int)
    for i in range(n):
        distances = np.linalg.norm(instance[i] - instance, axis=1)
        sorted_indices = np.argsort(distances)
        neighborhood_matrix[i] = sorted_indices
    return neighborhood_matrix


def _replay_instance(problem, alg, instance_id, instance, distance_matrix, trace_prefix_steps):
    destination_node = 0
    current_node = 0
    route = np.zeros(problem.problem_size)
    neighbor_matrix = _generate_neighborhood_matrix(instance)

    chosen_nodes = []
    chosen_distance_group_sizes = []
    duplicate_distance_hits = 0
    chosen_distance_tie_hits = 0
    traced_steps = []

    for step_index in range(1, problem.problem_size - 1):
        near_nodes = neighbor_matrix[current_node][1:]
        mask = ~np.isin(near_nodes, route[:step_index])
        unvisited_near_nodes = near_nodes[mask]
        unvisited_near_size = np.minimum(problem.neighbor_size, unvisited_near_nodes.size)
        unvisited_near_nodes = unvisited_near_nodes[:unvisited_near_size]

        candidate_distances = np.asarray(distance_matrix[current_node][unvisited_near_nodes], dtype=np.float64)
        rounded_distances = np.round(candidate_distances, 12)
        unique_distances, counts = np.unique(rounded_distances, return_counts=True)
        duplicate_count = int(len(unvisited_near_nodes) - len(unique_distances))
        if duplicate_count > 0:
            duplicate_distance_hits += 1

        next_node = int(alg.select_next_node(current_node, destination_node, unvisited_near_nodes, distance_matrix))
        if next_node in route:
            raise ValueError("algorithm selected duplicate node")
        if next_node not in unvisited_near_nodes:
            raise ValueError("algorithm selected node outside allowed neighborhood")

        chosen_local_index = int(np.where(unvisited_near_nodes == next_node)[0][0])
        chosen_distance = float(candidate_distances[chosen_local_index])
        chosen_distance_group_size = int(counts[unique_distances == np.round(chosen_distance, 12)][0])
        chosen_distance_group_sizes.append(chosen_distance_group_size)
        if chosen_distance_group_size > 1:
            chosen_distance_tie_hits += 1

        route[step_index] = next_node
        chosen_nodes.append(next_node)

        if step_index - 1 < trace_prefix_steps:
            traced_steps.append(
                {
                    "step_index": int(step_index - 1),
                    "current_node": int(current_node),
                    "candidate_count": int(len(unvisited_near_nodes)),
                    "duplicate_distance_count": duplicate_count,
                    "chosen_node": int(next_node),
                    "chosen_local_index": chosen_local_index,
                    "chosen_distance": chosen_distance,
                    "chosen_distance_group_size": chosen_distance_group_size,
                }
            )

        current_node = next_node

    mask = ~np.isin(np.arange(problem.problem_size), route[: problem.problem_size - 1])
    last_node = np.arange(problem.problem_size)[mask]
    current_node = int(last_node[0])
    route[problem.problem_size - 1] = current_node
    chosen_nodes.append(current_node)

    tour_cost = _tour_cost(instance, route, problem.problem_size)

    return {
        "instance_id": instance_id,
        "tour_cost": tour_cost,
        "route": route.astype(int).tolist(),
        "trace_steps": traced_steps,
        "choice_trace_signature": sha256_json(
            [
                {
                    "step_index": step["step_index"],
                    "current_node": step["current_node"],
                    "chosen_node": step["chosen_node"],
                    "chosen_local_index": step["chosen_local_index"],
                }
                for step in traced_steps
            ]
        ),
        "score_trace_signature": None,
        "decision_metrics": {
            "trace_length": len(traced_steps),
            "unique_bins_chosen": int(len(set(chosen_nodes))),
            "decision_entropy": float(_decision_entropy(chosen_nodes)),
            "top1_top2_margin_mean": None,
            "top1_top2_margin_std": None,
            "tie_hit_rate": float(chosen_distance_tie_hits / max(1, len(traced_steps))) if traced_steps else None,
            "duplicate_capacity_rate": float(duplicate_distance_hits / max(1, len(traced_steps))) if traced_steps else None,
            "mean_chosen_capacity_group_size": float(np.mean(chosen_distance_group_sizes)) if chosen_distance_group_sizes else None,
            "bin_opening_ratio_first_third": None,
            "mean_leftover_after_placement": None,
            "var_leftover_after_placement": None,
            "near_full_placement_ratio": None,
            "near_empty_placement_ratio": None,
        },
    }


class TSPConstructTraceExtractor:
    def __init__(self, problem, trace_config):
        self.problem = problem
        self.trace_config = trace_config

    def evaluate_candidate(self, code_string, use_numba):
        evaluation_code = build_evaluation_code(code_string, use_numba)
        alg = load_algorithm_module(evaluation_code)

        trace_prefix_steps = int(self.trace_config.get("trace_prefix_steps", 25))
        traced_instance_ids = set(self.trace_config.get("traced_instance_ids") or [0, 1])

        per_instance_scores = {}
        per_instance_outcomes = {}
        traced_instances = {}

        for index, (instance, distance_matrix) in enumerate(self.problem.instance_data):
            instance_id = f"instance_{index}"
            replay = _replay_instance(
                self.problem,
                alg,
                instance_id,
                instance,
                distance_matrix,
                trace_prefix_steps=trace_prefix_steps if index in traced_instance_ids or instance_id in traced_instance_ids else 0,
            )
            per_instance_scores[instance_id] = replay["tour_cost"]
            per_instance_outcomes[instance_id] = replay["tour_cost"]
            if index in traced_instance_ids or instance_id in traced_instance_ids:
                traced_instances[instance_id] = replay

        avg_cost = float(np.mean(list(per_instance_scores.values()))) if per_instance_scores else None

        return {
            "evaluation_code": evaluation_code,
            "full_search_metrics": {
                "per_instance_scores": per_instance_scores,
                "per_instance_bins_used": {},
                "per_instance_outcomes": per_instance_outcomes,
                "valid_instance_count": len(per_instance_scores),
                "search_problem_metrics": [
                    {
                        "problem_name": "tsp_construct",
                        "avg_tour_cost": avg_cost,
                        "fitness": avg_cost,
                    }
                ],
            },
            "traced_instance_metrics": {
                "instance_ids": sorted(traced_instances.keys()),
                "per_instance_scores": {key: value["tour_cost"] for key, value in traced_instances.items()},
                "per_instance_bins_used": {},
                "per_instance_outcomes": {key: value["tour_cost"] for key, value in traced_instances.items()},
            },
            "traces": traced_instances,
            "robustness": {
                "permuted_order_score_drop": None,
                "permuted_order_trace_change_rate": None,
                "instance_variance_bins_used": None,
                "instance_variance_score": _float_or_none(np.var(list(per_instance_scores.values()))) if per_instance_scores else None,
            },
        }
