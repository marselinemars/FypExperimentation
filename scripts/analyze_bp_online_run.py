import argparse
import hashlib
import json
import math
import os
import re
import sys
import types
from datetime import datetime, timezone

import numpy as np


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EOH_SRC = os.path.join(REPO_ROOT, "eoh", "src")
if EOH_SRC not in sys.path:
    sys.path.insert(0, EOH_SRC)

from eoh.methods.eoh.evaluator_accelerate import add_numba_decorator
from eoh.problems.optimization.bp_online.run import BPONLINE


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def sanitize_json_value(value):
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return sanitize_json_value(value.item())
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
    return value


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def latest_run_dir(base_runs_dir):
    run_dirs = [
        os.path.join(base_runs_dir, name)
        for name in os.listdir(base_runs_dir)
        if os.path.isdir(os.path.join(base_runs_dir, name))
    ]
    if not run_dirs:
        raise FileNotFoundError(f"No run directories found in {base_runs_dir}")
    return max(run_dirs, key=os.path.getmtime)


def sha256_text(value):
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_response_to_code(response_text, prompt_outputs):
    algorithm = re.findall(r"\{(.*)\}", response_text, re.DOTALL)
    if len(algorithm) == 0:
        if "python" in response_text:
            algorithm = re.findall(r"^.*?(?=python)", response_text, re.DOTALL)
        elif "import" in response_text:
            algorithm = re.findall(r"^.*?(?=import)", response_text, re.DOTALL)
        else:
            algorithm = re.findall(r"^.*?(?=def)", response_text, re.DOTALL)

    code = re.findall(r"import.*return", response_text, re.DOTALL)
    if len(code) == 0:
        code = re.findall(r"def.*return", response_text, re.DOTALL)

    if len(algorithm) == 0 or len(code) == 0:
        return None

    return {
        "algorithm": algorithm[0],
        "code": code[0] + " " + ", ".join(prompt_outputs),
    }


def reconstruct_candidate(record, prompt_outputs):
    trace = record.get("llm_trace_files") or {}
    response_files = trace.get("response_files") or []
    target_raw_hash = record.get("raw_code_sha256")

    for response_file in response_files:
        with open(response_file, "r", encoding="utf-8") as file:
            response_text = file.read()
        parsed = parse_response_to_code(response_text, prompt_outputs)
        if parsed is None:
            continue
        if target_raw_hash is None or sha256_text(parsed["code"]) == target_raw_hash:
            parsed["response_file"] = response_file
            return parsed

    return None


def build_evaluation_code(code, use_numba):
    if not use_numba:
        return code
    match = re.search(r"def\s+(\w+)\s*\(.*\):", code)
    if match is None:
        raise ValueError("unable to identify function name for numba decoration")
    return add_numba_decorator(program=code, function_name=match.group(1))


def load_algorithm_module(code_string):
    module = types.ModuleType("diagnostic_heuristic_module")
    exec(code_string, module.__dict__)
    return module


def trace_online_binpack(problem, items, capacity, alg, max_steps):
    bins = np.array([capacity for _ in range(len(items))])
    trace = []
    for step_index, item in enumerate(items[:max_steps]):
        valid_bin_indices = problem.get_valid_bin_indices(item, bins)
        valid_bins = bins[valid_bin_indices]
        unique_capacities, counts = np.unique(valid_bins, return_counts=True)
        chosen_capacity_group_size = 1
        priorities = alg.score(item, bins[valid_bin_indices])
        best_bin = valid_bin_indices[np.argmax(priorities)]
        chosen_capacity = bins[best_bin]
        chosen_capacity_matches = counts[unique_capacities == chosen_capacity]
        if len(chosen_capacity_matches) > 0:
            chosen_capacity_group_size = int(chosen_capacity_matches[0])
        trace.append(
            {
                "step_index": int(step_index),
                "item": int(item),
                "valid_bin_count": int(len(valid_bin_indices)),
                "unique_capacity_count": int(len(unique_capacities)),
                "duplicate_capacity_count": int(len(valid_bin_indices) - len(unique_capacities)),
                "max_equal_capacity_group_size": int(np.max(counts)),
                "chosen_capacity_group_size": chosen_capacity_group_size,
                "chosen_bin_index": int(best_bin),
                "priority_argmax_index": int(np.argmax(priorities)),
                "priority_max": float(np.max(priorities)),
            }
        )
        bins[best_bin] -= item
    return trace


def choice_signature_from_steps(steps):
    return [
        {
            "step_index": step["step_index"],
            "item": step["item"],
            "chosen_bin_index": step["chosen_bin_index"],
            "priority_argmax_index": step["priority_argmax_index"],
        }
        for step in steps
    ]


def analyze_capacity_ties(problem, items, capacity, alg, max_steps=None):
    bins = np.array([capacity for _ in range(len(items))])
    steps_to_analyze = items if max_steps is None else items[:max_steps]
    summary = {
        "step_count": 0,
        "steps_with_duplicate_valid_capacities": 0,
        "steps_with_chosen_capacity_tie": 0,
        "max_equal_capacity_group_size_observed": 0,
        "mean_duplicate_capacity_fraction": 0.0,
        "mean_chosen_capacity_group_size": 0.0,
    }
    duplicate_capacity_fractions = []
    chosen_capacity_group_sizes = []

    for item in steps_to_analyze:
        valid_bin_indices = problem.get_valid_bin_indices(item, bins)
        valid_bins = bins[valid_bin_indices]
        unique_capacities, counts = np.unique(valid_bins, return_counts=True)
        duplicate_capacity_count = int(len(valid_bin_indices) - len(unique_capacities))
        max_group_size = int(np.max(counts))
        priorities = alg.score(item, valid_bins)
        best_bin = valid_bin_indices[np.argmax(priorities)]

        summary["step_count"] += 1
        if duplicate_capacity_count > 0:
            summary["steps_with_duplicate_valid_capacities"] += 1
        summary["max_equal_capacity_group_size_observed"] = max(
            summary["max_equal_capacity_group_size_observed"],
            max_group_size,
        )
        duplicate_capacity_fractions.append(duplicate_capacity_count / len(valid_bin_indices))

        chosen_capacity = bins[best_bin]
        chosen_capacity_group_size = int(counts[unique_capacities == chosen_capacity][0])
        if chosen_capacity_group_size > 1:
            summary["steps_with_chosen_capacity_tie"] += 1
        chosen_capacity_group_sizes.append(chosen_capacity_group_size)

        bins[best_bin] -= item

    if summary["step_count"] > 0:
        summary["mean_duplicate_capacity_fraction"] = float(np.mean(duplicate_capacity_fractions))
        summary["mean_chosen_capacity_group_size"] = float(np.mean(chosen_capacity_group_sizes))

    return summary


def evaluate_candidate(problem, evaluation_code, trace_steps):
    alg = load_algorithm_module(evaluation_code)
    search_problem_metrics = []
    first_trace = None
    first_capacity_tie_summary = None

    for problem_name, dataset in problem.instances.items():
        instance_bin_counts = []
        for instance_key, instance in dataset.items():
            capacity = instance["capacity"]
            items = np.array(instance["items"])
            bins = np.array([capacity for _ in range(instance["num_items"])])
            _, bins_packed = problem.online_binpack(items, bins, alg)
            used_bins = int((bins_packed != capacity).sum())
            instance_bin_counts.append(
                {
                    "instance_id": instance_key,
                    "used_bins": used_bins,
                }
            )
            if first_trace is None:
                first_trace = {
                    "problem_name": problem_name,
                    "instance_id": instance_key,
                    "steps": trace_online_binpack(problem, items, capacity, alg, trace_steps),
                }
                first_capacity_tie_summary = {
                    "problem_name": problem_name,
                    "instance_id": instance_key,
                    "full_instance": analyze_capacity_ties(problem, items, capacity, alg, max_steps=None),
                    "traced_prefix": analyze_capacity_ties(problem, items, capacity, alg, max_steps=trace_steps),
                }

        avg_num_bins = float(np.mean([entry["used_bins"] for entry in instance_bin_counts]))
        lower_bound = float(problem.lb[problem_name])
        fitness = float((avg_num_bins - lower_bound) / lower_bound)
        search_problem_metrics.append(
            {
                "problem_name": problem_name,
                "avg_num_bins": avg_num_bins,
                "lower_bound": lower_bound,
                "fitness": fitness,
                "instance_bin_counts": instance_bin_counts,
            }
        )

    return {
        "problem_metrics": search_problem_metrics,
        "trace": first_trace,
        "capacity_tie_summary": first_capacity_tie_summary,
    }


def summarize_candidates(candidate_results):
    fitness_signatures = {}
    decision_signatures = {}
    choice_signatures = {}
    for result in candidate_results:
        metrics = result["diagnostics"]["problem_metrics"]
        trace = result["diagnostics"]["trace"] or {}
        steps = trace.get("steps") or []
        fitness_signature = json.dumps(
            [
                {
                    "problem_name": metric["problem_name"],
                    "used_bins": [entry["used_bins"] for entry in metric["instance_bin_counts"]],
                }
                for metric in metrics
            ],
            sort_keys=True,
        )
        decision_signature = json.dumps(steps, sort_keys=True)
        choice_signature = json.dumps(choice_signature_from_steps(steps), sort_keys=True)
        fitness_signatures.setdefault(fitness_signature, []).append(result["attempt_id"])
        decision_signatures.setdefault(decision_signature, []).append(result["attempt_id"])
        choice_signatures.setdefault(choice_signature, []).append(result["attempt_id"])

    return {
        "candidate_count": len(candidate_results),
        "unique_per_instance_bin_count_signatures": len(fitness_signatures),
        "unique_trace_signatures": len(decision_signatures),
        "unique_choice_trace_signatures": len(choice_signatures),
        "fitness_signature_groups": list(fitness_signatures.values()),
        "trace_signature_groups": list(decision_signatures.values()),
        "choice_trace_signature_groups": list(choice_signatures.values()),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose whether bp_online candidates with tied fitness are behaviorally identical."
    )
    parser.add_argument("--run-dir", help="Run directory. Defaults to the latest under ./runs.")
    parser.add_argument("--max-candidates", type=int, default=8, help="Maximum number of valid candidates to analyze.")
    parser.add_argument("--trace-steps", type=int, default=10, help="Number of initial placement steps to trace.")
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir) if args.run_dir else latest_run_dir(os.path.join(REPO_ROOT, "runs"))
    attempts_path = os.path.join(run_dir, "logs", "candidate_attempts.jsonl")
    summary_path = os.path.join(run_dir, "run_summary.json")
    output_dir = os.path.join(run_dir, "analysis")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "bp_online_candidate_diagnostics.json")

    attempts = load_jsonl(attempts_path)
    run_summary = load_json(summary_path)
    problem = BPONLINE()
    prompt_outputs = problem.prompts.get_func_outputs()

    valid_attempts = [record for record in attempts if record.get("status") == "valid"]
    unique_candidates = []
    seen_code_hashes = set()
    for record in valid_attempts:
        code_hash = record.get("code_sha256")
        if code_hash in seen_code_hashes:
            continue
        seen_code_hashes.add(code_hash)
        unique_candidates.append(record)
        if len(unique_candidates) >= args.max_candidates:
            break

    candidate_results = []
    reconstruction_failures = []
    for record in unique_candidates:
        reconstructed = reconstruct_candidate(record, prompt_outputs)
        if reconstructed is None:
            reconstruction_failures.append(
                {
                    "attempt_id": record.get("attempt_id"),
                    "reason": "unable_to_reconstruct_candidate_from_response_files",
                }
            )
            continue

        try:
            evaluation_code = build_evaluation_code(reconstructed["code"], record.get("used_numba"))
            diagnostics = evaluate_candidate(problem, evaluation_code, args.trace_steps)
            candidate_results.append(
                {
                    "attempt_id": record.get("attempt_id"),
                    "operator": record.get("operator"),
                    "logged_objective": record.get("objective"),
                    "code_sha256": record.get("code_sha256"),
                    "raw_code_sha256": record.get("raw_code_sha256"),
                    "algorithm_sha256": record.get("algorithm_sha256"),
                    "response_file": reconstructed.get("response_file"),
                    "diagnostics": diagnostics,
                }
            )
        except Exception as exc:
            reconstruction_failures.append(
                {
                    "attempt_id": record.get("attempt_id"),
                    "reason": "diagnostic_evaluation_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )

    payload = {
        "generated_at_utc": utc_now_iso(),
        "run_dir": run_dir,
        "run_id": run_summary.get("run_id"),
        "analyzed_candidate_count": len(candidate_results),
        "requested_max_candidates": args.max_candidates,
        "trace_steps": args.trace_steps,
        "summary": summarize_candidates(candidate_results),
        "candidate_results": candidate_results,
        "reconstruction_failures": reconstruction_failures,
    }
    payload = sanitize_json_value(payload)

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, allow_nan=False)

    print(json.dumps(payload["summary"], indent=2))
    print(f"Saved diagnostics to {output_path}")


if __name__ == "__main__":
    main()
