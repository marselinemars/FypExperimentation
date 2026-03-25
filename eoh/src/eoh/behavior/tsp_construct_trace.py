import math
import types

import numpy as np


def _safe_float(value):
    try:
        value = float(value)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return value


def _load_algorithm_module(code_string):
    module = types.ModuleType("behavior_trace_module")
    exec(code_string, module.__dict__)
    return module


def _instance_id(index):
    return f"instance_{index}"


def _normalize_traced_instance_ids(trace_config, total_instances):
    configured = trace_config.get("traced_instance_ids") or []
    normalized = set()
    for value in configured:
        if isinstance(value, int):
            normalized.add(_instance_id(value))
            continue
        if isinstance(value, str) and value.startswith("instance_"):
            normalized.add(value)
            continue
        try:
            normalized.add(_instance_id(int(value)))
        except Exception:
            continue

    if normalized:
        return normalized

    default_count = int(trace_config.get("traced_instance_count", min(2, total_instances)))
    return {_instance_id(index) for index in range(min(total_instances, default_count))}


def _duplicate_distance_count(distances, epsilon):
    if len(distances) <= 1:
        return 0
    sorted_values = np.sort(np.asarray(distances, dtype=np.float64))
    unique_count = 1
    previous = float(sorted_values[0])
    for value in sorted_values[1:]:
        value = float(value)
        if abs(value - previous) > epsilon:
            unique_count += 1
            previous = value
    return int(len(sorted_values) - unique_count)


def _chosen_distance_group_size(distances, chosen_distance, epsilon):
    if chosen_distance is None:
        return None
    count = 0
    for value in distances:
        if abs(float(value) - float(chosen_distance)) <= epsilon:
            count += 1
    return int(count)


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


def _replay_instance(problem, alg, coordinates, distance_matrix, start_node, trace_prefix_steps, distance_tie_epsilon):
    problem_size = problem.problem_size
    neighbor_matrix = problem.generate_neighborhood_matrix(coordinates)
    destination_node = int(start_node)
    current_node = int(start_node)
    route = np.full(problem_size, -1, dtype=int)
    route[0] = current_node

    traced_steps = []

    for step_index in range(1, problem_size - 1):
        near_nodes = neighbor_matrix[current_node][1:]
        mask = ~np.isin(near_nodes, route[:step_index])
        unvisited_near_nodes = near_nodes[mask]
        unvisited_near_nodes = unvisited_near_nodes[: np.minimum(problem.neighbor_size, unvisited_near_nodes.size)]

        chosen_node = int(alg.select_next_node(current_node, destination_node, unvisited_near_nodes, distance_matrix))
        if chosen_node in route[:step_index]:
            raise ValueError("select_next_node chose a duplicate node already present in the route")

        chosen_rank = None
        chosen_rank_ratio = None
        chosen_edge_length = None
        chosen_distance_group_size = None
        duplicate_distance_count = 0

        if len(unvisited_near_nodes) > 0:
            candidate_distances = np.asarray(distance_matrix[current_node][unvisited_near_nodes], dtype=np.float64)
            duplicate_distance_count = _duplicate_distance_count(candidate_distances, distance_tie_epsilon)
            positions = np.where(unvisited_near_nodes == chosen_node)[0]
            if len(positions) > 0:
                chosen_rank = int(positions[0])
                chosen_rank_ratio = float(chosen_rank / max(len(unvisited_near_nodes) - 1, 1))
                chosen_edge_length = _safe_float(distance_matrix[current_node][chosen_node])
                chosen_distance_group_size = _chosen_distance_group_size(
                    candidate_distances,
                    chosen_edge_length,
                    distance_tie_epsilon,
                )

        previous_node = int(current_node)
        current_node = chosen_node
        route[step_index] = current_node

        if len(traced_steps) < trace_prefix_steps:
            traced_steps.append(
                {
                    "step_index": int(step_index - 1),
                    "current_node": previous_node,
                    "chosen_node": int(chosen_node),
                    "candidate_count": int(len(unvisited_near_nodes)),
                    "chosen_rank": chosen_rank,
                    "chosen_rank_ratio": chosen_rank_ratio,
                    "chosen_edge_length": chosen_edge_length,
                    "duplicate_distance_count": int(duplicate_distance_count),
                    "chosen_distance_group_size": chosen_distance_group_size,
                    "rank_bucket": _rank_bucket(chosen_rank_ratio),
                }
            )

    mask = ~np.isin(np.arange(problem_size), route[: problem_size - 1])
    last_node = np.arange(problem_size)[mask]
    if len(last_node) != 1:
        raise ValueError("unable to identify final unvisited TSP node")
    route[problem_size - 1] = int(last_node[0])

    tour_length = _safe_float(problem.tour_cost(coordinates, route, problem_size))
    return {
        "route": route.tolist(),
        "tour_length": tour_length,
        "trace_steps": traced_steps,
        "full_step_count": int(problem_size - 2),
        "start_node": int(start_node),
    }


class TSPConstructTraceExtractor:
    def __init__(self, problem, trace_config):
        self.problem = problem
        self.trace_config = trace_config

    def evaluate_candidate(self, code_string, use_numba):
        del use_numba
        alg = _load_algorithm_module(code_string)

        total_instances = len(self.problem.instance_data)
        traced_instance_ids = _normalize_traced_instance_ids(self.trace_config, total_instances)
        trace_prefix_steps = int(self.trace_config.get("trace_prefix_steps", self.problem.problem_size))
        distance_tie_epsilon = float(self.trace_config.get("distance_tie_epsilon", 1e-12))

        full_search_tour_length = {}
        traced_instances = {}

        for index, (coordinates, distance_matrix) in enumerate(self.problem.instance_data):
            instance_id = _instance_id(index)
            replay = _replay_instance(
                self.problem,
                alg,
                coordinates,
                distance_matrix,
                start_node=0,
                trace_prefix_steps=trace_prefix_steps if instance_id in traced_instance_ids else 0,
                distance_tie_epsilon=distance_tie_epsilon,
            )
            full_search_tour_length[instance_id] = replay["tour_length"]
            if instance_id in traced_instance_ids:
                traced_instances[instance_id] = replay

        mean_tour_length = _safe_float(np.mean(list(full_search_tour_length.values()))) if full_search_tour_length else None

        return {
            "full_search_metrics": {
                "per_instance_tour_length": dict(full_search_tour_length),
                "per_instance_outcomes": dict(full_search_tour_length),
                "valid_instance_count": len(full_search_tour_length),
                "search_problem_metrics": [
                    {
                        "problem_name": "tsp_construct",
                        "avg_tour_length": mean_tour_length,
                    }
                ],
            },
            "traced_instance_metrics": {
                "instance_ids": sorted(traced_instances.keys()),
                "per_instance_tour_length": {key: value["tour_length"] for key, value in traced_instances.items()},
                "per_instance_outcomes": {key: value["tour_length"] for key, value in traced_instances.items()},
            },
            "traces": traced_instances,
            "robustness": self._evaluate_alternate_starts(
                alg,
                traced_instance_ids=traced_instance_ids,
                trace_prefix_steps=trace_prefix_steps,
                distance_tie_epsilon=distance_tie_epsilon,
            ),
        }

    def _evaluate_alternate_starts(self, alg, traced_instance_ids, trace_prefix_steps, distance_tie_epsilon):
        alternate_start_nodes = [int(value) for value in (self.trace_config.get("alternate_start_nodes") or [1])]
        base_scores = []
        alt_scores = []
        change_rates = []

        for index, (coordinates, distance_matrix) in enumerate(self.problem.instance_data):
            instance_id = _instance_id(index)
            if instance_id not in traced_instance_ids:
                continue

            baseline = _replay_instance(
                self.problem,
                alg,
                coordinates,
                distance_matrix,
                start_node=0,
                trace_prefix_steps=trace_prefix_steps,
                distance_tie_epsilon=distance_tie_epsilon,
            )
            base_scores.append(baseline["tour_length"])

            for start_node in alternate_start_nodes:
                if start_node <= 0 or start_node >= self.problem.problem_size:
                    continue
                alternate = _replay_instance(
                    self.problem,
                    alg,
                    coordinates,
                    distance_matrix,
                    start_node=start_node,
                    trace_prefix_steps=trace_prefix_steps,
                    distance_tie_epsilon=distance_tie_epsilon,
                )
                alt_scores.append(alternate["tour_length"])

                baseline_buckets = [step.get("rank_bucket") for step in baseline["trace_steps"]]
                alternate_buckets = [step.get("rank_bucket") for step in alternate["trace_steps"]]
                compared = min(len(baseline_buckets), len(alternate_buckets))
                if compared == 0:
                    continue
                changed = sum(
                    1
                    for step_index in range(compared)
                    if baseline_buckets[step_index] != alternate_buckets[step_index]
                )
                change_rates.append(changed / compared)

        score_delta = None
        if base_scores and alt_scores:
            baseline_mean = float(np.mean(base_scores))
            alternate_mean = float(np.mean(alt_scores))
            score_delta = _safe_float((alternate_mean - baseline_mean) / max(abs(baseline_mean), 1e-12))

        instance_variance = _safe_float(np.var(list(base_scores))) if base_scores else None
        instance_cv = None
        if base_scores:
            baseline_mean = float(np.mean(base_scores))
            if abs(baseline_mean) > 1e-12:
                instance_cv = _safe_float(np.std(base_scores) / abs(baseline_mean))

        return {
            "alt_start_relative_score_delta": score_delta,
            "alt_start_trace_change_rate": _safe_float(np.mean(change_rates)) if change_rates else None,
            "instance_variance_tour_length": instance_variance,
            "instance_cv_tour_length": instance_cv,
        }
