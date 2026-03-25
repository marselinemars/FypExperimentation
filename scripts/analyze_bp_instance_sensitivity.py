import argparse
import copy
import glob
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
    if isinstance(value, float) and not math.isfinite(value):
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


def sha256_json(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    if len(code) == 0:
        fenced = re.findall(r"```(?:python)?\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
        for block in fenced:
            if "def " in block and "return" in block:
                code = [block.strip()]
                break

    if len(code) == 0:
        return None

    return {
        "algorithm": algorithm[0] if algorithm else "unavailable",
        "code": code[0] + " " + ", ".join(prompt_outputs),
    }


def reconstruct_candidate(record, prompt_outputs):
    trace = record.get("llm_trace_files") or {}
    response_files = trace.get("response_files") or []
    target_raw_hash = record.get("raw_code_sha256") or record.get("code_sha256")
    first_parsed = None

    for response_file in response_files:
        if not os.path.exists(response_file):
            continue
        with open(response_file, "r", encoding="utf-8") as file:
            response_text = file.read()
        parsed = parse_response_to_code(response_text, prompt_outputs)
        if parsed is None:
            continue
        if first_parsed is None:
            first_parsed = dict(parsed)
            first_parsed["response_file"] = response_file
            first_parsed["hash_match"] = False
        if target_raw_hash is None or sha256_text(parsed["code"]) == target_raw_hash:
            parsed["response_file"] = response_file
            parsed["hash_match"] = True
            return parsed

    return first_parsed


def discover_candidate_records(run_dir):
    manifest_path = os.path.join(run_dir, "run_manifest.json")
    manifest = load_json(manifest_path) if os.path.exists(manifest_path) else {}
    manifest_paras = manifest.get("paras") or {}
    default_used_numba = bool(manifest_paras.get("eva_numba_decorator"))

    attempts_path = os.path.join(run_dir, "logs", "candidate_attempts.jsonl")
    attempts = load_jsonl(attempts_path) if os.path.exists(attempts_path) else []
    attempts_by_id = {
        record.get("attempt_id"): record
        for record in attempts
        if record.get("attempt_id")
    }

    cards_dir = os.path.join(run_dir, "behavior", "cards")
    cards = []
    if os.path.isdir(cards_dir):
        for path in sorted(glob.glob(os.path.join(cards_dir, "candidate_*.json"))):
            try:
                cards.append(load_json(path))
            except Exception:
                continue
    cards_by_id = {
        (card.get("identity") or {}).get("candidate_id"): card
        for card in cards
        if (card.get("identity") or {}).get("candidate_id")
    }

    response_dirs = [
        os.path.join(run_dir, "logs", "responses"),
        os.path.join(run_dir, "behavior", "logs", "responses"),
    ]
    response_files_by_id = {}
    for responses_dir in response_dirs:
        if not os.path.isdir(responses_dir):
            continue
        for path in sorted(glob.glob(os.path.join(responses_dir, "*__response_*.txt"))):
            candidate_id = os.path.basename(path).split("__", 1)[0]
            if not candidate_id:
                continue
            response_files_by_id.setdefault(candidate_id, []).append(path)

    discovered = []
    seen_ids = set()
    all_candidate_ids = sorted(set(response_files_by_id.keys()) | set(attempts_by_id.keys()) | set(cards_by_id.keys()))

    for attempt_id in all_candidate_ids:
        if not attempt_id or attempt_id in seen_ids:
            continue
        card = cards_by_id.get(attempt_id) or {}
        identity = card.get("identity") or {}
        attempt = attempts_by_id.get(attempt_id) or {}
        response_files = (
            response_files_by_id.get(attempt_id)
            or ((attempt.get("llm_trace_files") or {}).get("response_files"))
            or []
        )
        if not response_files and not identity and not attempt:
            continue

        status = None
        if attempt.get("status") is not None:
            status = attempt.get("status")
        elif identity.get("valid") is True:
            status = "valid"
        elif identity.get("valid") is False:
            status = "invalid"

        source_parts = []
        if response_files:
            source_parts.append("response_files")
        if identity:
            source_parts.append("behavior_card")
        if attempt:
            source_parts.append("candidate_attempt")

        discovered.append(
            {
                "attempt_id": attempt_id,
                "operator": identity.get("operator") or attempt.get("operator"),
                "objective": identity.get("objective") if identity.get("objective") is not None else attempt.get("objective"),
                "code_sha256": identity.get("code_hash") or attempt.get("code_sha256"),
                "raw_code_sha256": attempt.get("raw_code_sha256") or identity.get("code_hash") or attempt.get("code_sha256"),
                "used_numba": attempt.get("used_numba", default_used_numba),
                "status": status,
                "llm_trace_files": {
                    "response_files": response_files,
                },
                "source": "+".join(source_parts) if source_parts else "unknown",
            }
        )
        seen_ids.add(attempt_id)

    return {
        "manifest": manifest,
        "attempts_present": bool(attempts),
        "cards_present": bool(cards),
        "responses_present": bool(response_files_by_id),
        "response_dirs_checked": response_dirs,
        "candidate_records": discovered,
    }


def build_evaluation_code(code, use_numba):
    if not use_numba:
        return code
    match = re.search(r"def\s+(\w+)\s*\(.*\):", code)
    if match is None:
        raise ValueError("unable to identify function name for numba decoration")
    return add_numba_decorator(program=code, function_name=match.group(1))


def load_algorithm_module(code_string):
    module = types.ModuleType("instance_sensitivity_module")
    exec(code_string, module.__dict__)
    return module


def instance_l1_bound(items, capacity):
    return float(np.ceil(np.sum(items) / capacity))


def compute_dataset_lb(dataset):
    return float(np.mean([instance_l1_bound(instance["items"], instance["capacity"]) for instance in dataset.values()]))


def clone_problem_with_dataset(base_problem, dataset_name, dataset):
    clone = BPONLINE()
    clone.instances = {dataset_name: dataset}
    clone.lb = {dataset_name: compute_dataset_lb(dataset)}
    return clone


def perturb_dataset(dataset, mode, seed):
    rng = np.random.default_rng(seed)
    perturbed = {}
    for instance_id, instance in dataset.items():
        items = np.array(instance["items"])
        if mode == "permute":
            new_items = items[rng.permutation(len(items))]
        elif mode == "reverse":
            new_items = items[::-1]
        elif mode == "sorted_desc":
            new_items = np.sort(items)[::-1]
        else:
            raise ValueError(f"Unsupported perturbation mode: {mode}")
        perturbed[instance_id] = {
            "capacity": instance["capacity"],
            "num_items": instance["num_items"],
            "items": new_items.tolist(),
        }
    return perturbed


def evaluate_candidate_on_instance(problem, alg, instance_id, instance, trace_steps, tie_score_epsilon):
    capacity = instance["capacity"]
    items = np.array(instance["items"])
    bins = np.array([capacity for _ in range(instance["num_items"])], dtype=np.float64)

    chosen_bins = []
    traced_steps_payload = []
    duplicate_capacity_steps = 0
    tie_hit_steps = 0
    margins = []

    for step_index, item in enumerate(items):
        valid_bin_indices = problem.get_valid_bin_indices(item, bins)
        valid_bins = bins[valid_bin_indices]
        unique_capacities, counts = np.unique(valid_bins, return_counts=True)
        if len(valid_bin_indices) - len(unique_capacities) > 0:
            duplicate_capacity_steps += 1

        priorities = np.asarray(alg.score(item, valid_bins))
        if priorities.ndim != 1 or len(priorities) != len(valid_bin_indices):
            raise ValueError("score() output length does not match feasible bin count")

        best_local_index = int(np.argmax(priorities))
        sorted_indices = np.argsort(priorities)
        top1 = float(priorities[sorted_indices[-1]])
        top2 = float(priorities[sorted_indices[-2]]) if len(priorities) > 1 else None
        margin = (top1 - top2) if top2 is not None else None
        if margin is not None:
            margins.append(margin)
        tie_count = int(sum(1 for value in priorities if abs(float(value) - top1) <= tie_score_epsilon))
        if tie_count > 1:
            tie_hit_steps += 1

        best_bin = int(valid_bin_indices[best_local_index])
        chosen_bins.append(best_bin)
        bins[best_bin] -= item

        if step_index < trace_steps:
            traced_steps_payload.append(
                {
                    "step_index": int(step_index),
                    "item": int(item),
                    "chosen_bin_index": best_bin,
                    "priority_argmax_index": best_local_index,
                    "top1_top2_margin": margin,
                    "top_score_tie_count": tie_count,
                }
            )

    used_bins = int((bins != capacity).sum())
    score = float((used_bins - instance_l1_bound(items, capacity)) / instance_l1_bound(items, capacity))

    return {
        "instance_id": instance_id,
        "used_bins": used_bins,
        "instance_score": score,
        "choice_signature_full": sha256_json(chosen_bins),
        "choice_signature_prefix": sha256_json(traced_steps_payload),
        "duplicate_capacity_rate": float(duplicate_capacity_steps / len(items)) if len(items) else None,
        "tie_hit_rate": float(tie_hit_steps / len(items)) if len(items) else None,
        "mean_margin": float(np.mean(margins)) if margins else None,
    }


def analyze_dataset(problem, candidate_modules, dataset_name, dataset, trace_steps, tie_score_epsilon):
    instance_results = {instance_id: [] for instance_id in dataset.keys()}
    candidate_vectors = []

    for candidate in candidate_modules:
        per_instance = {}
        for instance_id, instance in dataset.items():
            result = evaluate_candidate_on_instance(
                problem,
                candidate["algorithm_module"],
                instance_id,
                instance,
                trace_steps,
                tie_score_epsilon,
            )
            per_instance[instance_id] = result
            instance_results[instance_id].append(
                {
                    "candidate_id": candidate["attempt_id"],
                    "choice_signature_full": result["choice_signature_full"],
                    "choice_signature_prefix": result["choice_signature_prefix"],
                    "used_bins": result["used_bins"],
                    "instance_score": result["instance_score"],
                }
            )

        candidate_vectors.append(
            {
                "candidate_id": candidate["attempt_id"],
                "used_bins_vector": {instance_id: per_instance[instance_id]["used_bins"] for instance_id in dataset.keys()},
                "choice_signature_vector": {instance_id: per_instance[instance_id]["choice_signature_full"] for instance_id in dataset.keys()},
            }
        )

    embedded_vector_groups = group_by_signature(
        [
            {
                "candidate_id": item["candidate_id"],
                "signature": sha256_json(item["used_bins_vector"]),
            }
            for item in candidate_vectors
        ]
    )

    return {
        "dataset_name": dataset_name,
        "candidate_count": len(candidate_modules),
        "per_instance_diversity": summarize_per_instance_diversity(instance_results),
        "vector_signature_summary": summarize_grouping(embedded_vector_groups, len(candidate_modules)),
        "candidate_vectors": candidate_vectors,
    }


def group_by_signature(records):
    groups = {}
    for record in records:
        groups.setdefault(record["signature"], []).append(record["candidate_id"])
    return groups


def summarize_grouping(groups, candidate_count):
    duplicate_candidate_count = sum(len(group) for group in groups.values() if len(group) > 1)
    return {
        "unique_signature_count": len(groups),
        "duplicate_group_count": sum(1 for group in groups.values() if len(group) > 1),
        "duplicate_candidate_count": duplicate_candidate_count,
        "duplicate_ratio": (duplicate_candidate_count / candidate_count) if candidate_count else None,
        "groups": list(groups.values()),
    }


def summarize_per_instance_diversity(instance_results):
    summary = {}
    for instance_id, records in instance_results.items():
        choice_groups = group_by_signature(
            [
                {
                    "candidate_id": record["candidate_id"],
                    "signature": record["choice_signature_full"],
                }
                for record in records
            ]
        )
        bins_groups = group_by_signature(
            [
                {
                    "candidate_id": record["candidate_id"],
                    "signature": str(record["used_bins"]),
                }
                for record in records
            ]
        )
        summary[instance_id] = {
            "unique_choice_signature_count": len(choice_groups),
            "choice_duplicate_ratio": summarize_grouping(choice_groups, len(records))["duplicate_ratio"],
            "unique_bins_used_count": len(bins_groups),
            "bins_used_values": sorted({record["used_bins"] for record in records}),
            "candidate_count": len(records),
        }
    return summary


def analyze_leave_one_out(dataset_name, dataset, candidate_modules):
    instance_ids = list(dataset.keys())
    candidate_count = len(candidate_modules)
    reports = []
    for omitted in instance_ids:
        signature_records = []
        for candidate in candidate_modules:
            subset_vector = {
                instance_id: candidate["embedded_results"][instance_id]["used_bins"]
                for instance_id in instance_ids
                if instance_id != omitted
            }
            signature_records.append(
                {
                    "candidate_id": candidate["attempt_id"],
                    "signature": sha256_json(subset_vector),
                }
            )
        grouping = summarize_grouping(group_by_signature(signature_records), candidate_count)
        reports.append(
            {
                "omitted_instance_id": omitted,
                "subset_unique_signature_count": grouping["unique_signature_count"],
                "subset_duplicate_ratio": grouping["duplicate_ratio"],
                "subset_duplicate_group_count": grouping["duplicate_group_count"],
            }
        )
    return reports


def attribution_verdict(embedded_report, perturbed_reports):
    embedded_unique = embedded_report["vector_signature_summary"]["unique_signature_count"]
    embedded_duplicate_ratio = embedded_report["vector_signature_summary"]["duplicate_ratio"]
    per_instance = embedded_report["per_instance_diversity"]
    all_embedded_instances_collapsed = all(
        item["unique_choice_signature_count"] == 1 for item in per_instance.values()
    )

    best_perturbed_unique = embedded_unique
    best_perturbed_duplicate_ratio = embedded_duplicate_ratio
    best_perturbed_name = None
    for report in perturbed_reports:
        unique_count = report["vector_signature_summary"]["unique_signature_count"]
        duplicate_ratio = report["vector_signature_summary"]["duplicate_ratio"]
        if unique_count > best_perturbed_unique:
            best_perturbed_unique = unique_count
            best_perturbed_duplicate_ratio = duplicate_ratio
            best_perturbed_name = report["variant_name"]

    perturbation_helps = best_perturbed_unique > embedded_unique and (
        best_perturbed_duplicate_ratio is not None
        and embedded_duplicate_ratio is not None
        and best_perturbed_duplicate_ratio < embedded_duplicate_ratio
    )

    if perturbation_helps and all_embedded_instances_collapsed:
        verdict = "both"
    elif perturbation_helps:
        verdict = "instance_set_driven"
    elif all_embedded_instances_collapsed:
        verdict = "evaluator_state_driven"
    else:
        verdict = "inconclusive"

    return {
        "verdict": verdict,
        "embedded_instances_all_collapsed": all_embedded_instances_collapsed,
        "best_perturbed_variant": best_perturbed_name,
        "best_perturbed_unique_signature_count": best_perturbed_unique,
        "best_perturbed_duplicate_ratio": best_perturbed_duplicate_ratio,
        "reasoning": {
            "embedded_unique_signature_count": embedded_unique,
            "embedded_duplicate_ratio": embedded_duplicate_ratio,
            "perturbation_helps": perturbation_helps,
        },
    }


def markdown_summary(report):
    lines = []
    lines.append("# BP Instance Sensitivity Report")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at_utc']}`")
    lines.append(f"- Run dir: `{report['run_dir']}`")
    lines.append(f"- Analyzed candidates: `{report['analyzed_candidate_count']}`")
    lines.append("")
    lines.append("## Answers")
    embedded = report["embedded_report"]
    per_instance = embedded["per_instance_diversity"]
    too_similar = all(item["unique_choice_signature_count"] == 1 for item in per_instance.values())
    lines.append(f"- Are the 5 embedded search instances behaviorally too similar? `{too_similar}`")

    leave_one_out = report["leave_one_out_report"]
    best_leave_one_out = max(leave_one_out, key=lambda item: item["subset_unique_signature_count"])
    dominant = best_leave_one_out["subset_unique_signature_count"] > embedded["vector_signature_summary"]["unique_signature_count"]
    lines.append(f"- Does one instance dominate the collapse? `{dominant}`")
    lines.append(f"  - Best leave-one-out case: omit `{best_leave_one_out['omitted_instance_id']}`, unique subset signatures = `{best_leave_one_out['subset_unique_signature_count']}`")

    perturbed = report["perturbed_reports"]
    best_perturbed = max(perturbed, key=lambda item: item["vector_signature_summary"]["unique_signature_count"]) if perturbed else None
    perturbed_more_diverse = (
        best_perturbed is not None
        and best_perturbed["vector_signature_summary"]["unique_signature_count"] > embedded["vector_signature_summary"]["unique_signature_count"]
    )
    lines.append(f"- Do alternative or perturbed instances produce more behavioral diversity? `{perturbed_more_diverse}`")
    if best_perturbed is not None:
        lines.append(
            f"  - Best perturbed set: `{best_perturbed['variant_name']}`, unique signatures = `{best_perturbed['vector_signature_summary']['unique_signature_count']}`, duplicate ratio = `{best_perturbed['vector_signature_summary']['duplicate_ratio']}`"
        )

    lines.append(f"- Is the collapse mainly instance-set driven, evaluator/state driven, or both? `{report['attribution']['verdict']}`")
    lines.append("")
    lines.append("## Embedded Set")
    for instance_id, item in per_instance.items():
        lines.append(
            f"- `{instance_id}`: unique choice signatures = `{item['unique_choice_signature_count']}`, unique bins-used values = `{item['unique_bins_used_count']}`, duplicate ratio = `{item['choice_duplicate_ratio']}`"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Analyze whether bp_online collapse is instance-set driven, evaluator/state driven, or both.")
    parser.add_argument("--run-dir", help="Run directory. Defaults to the latest under ./runs.")
    parser.add_argument("--max-candidates", type=int, default=8, help="Maximum number of valid candidates to analyze.")
    parser.add_argument("--trace-steps", type=int, default=200, help="Trace prefix length used inside per-instance behavior checks.")
    parser.add_argument("--perturbation-seed", type=int, default=2024, help="Seed for deterministic perturbed instance variants.")
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir) if args.run_dir else latest_run_dir(os.path.join(REPO_ROOT, "runs"))
    output_dir = os.path.join(run_dir, "analysis")
    os.makedirs(output_dir, exist_ok=True)
    json_output_path = os.path.join(output_dir, "bp_instance_sensitivity.json")
    md_output_path = os.path.join(output_dir, "bp_instance_sensitivity.md")

    discovery = discover_candidate_records(run_dir)
    candidate_records = discovery["candidate_records"]
    if not candidate_records:
        raise FileNotFoundError(
            "No analyzable valid candidates found. Expected either behavior cards under "
            f"'{os.path.join(run_dir, 'behavior', 'cards')}' or valid candidate records under "
            f"'{os.path.join(run_dir, 'logs', 'candidate_attempts.jsonl')}'."
        )

    base_problem = BPONLINE()
    prompt_outputs = base_problem.prompts.get_func_outputs()
    dataset_name, dataset = next(iter(base_problem.instances.items()))

    unique_candidates = []
    seen_code_hashes = set()
    for record in candidate_records:
        code_hash = record.get("code_sha256")
        if code_hash in seen_code_hashes:
            continue
        seen_code_hashes.add(code_hash)
        unique_candidates.append(record)
        if len(unique_candidates) >= args.max_candidates:
            break

    candidate_modules = []
    reconstruction_failures = []
    tie_score_epsilon = 1e-12

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
            algorithm_module = load_algorithm_module(evaluation_code)
            embedded_results = {}
            for instance_id, instance in dataset.items():
                embedded_results[instance_id] = evaluate_candidate_on_instance(
                    base_problem,
                    algorithm_module,
                    instance_id,
                    instance,
                    trace_steps=args.trace_steps,
                    tie_score_epsilon=tie_score_epsilon,
                )
            candidate_modules.append(
                {
                    "attempt_id": record.get("attempt_id"),
                    "operator": record.get("operator"),
                    "objective": record.get("objective"),
                    "code_sha256": record.get("code_sha256"),
                    "algorithm_module": algorithm_module,
                    "embedded_results": embedded_results,
                }
            )
        except Exception as exc:
            reconstruction_failures.append(
                {
                    "attempt_id": record.get("attempt_id"),
                    "reason": "candidate_replay_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )

    embedded_report = analyze_dataset(
        clone_problem_with_dataset(base_problem, dataset_name, dataset),
        candidate_modules,
        dataset_name,
        dataset,
        args.trace_steps,
        tie_score_epsilon,
    )
    leave_one_out_report = analyze_leave_one_out(dataset_name, dataset, candidate_modules)

    perturbed_variants = [
        ("permute_seed_2024", perturb_dataset(dataset, "permute", args.perturbation_seed)),
        ("reverse_order", perturb_dataset(dataset, "reverse", args.perturbation_seed)),
        ("sorted_desc", perturb_dataset(dataset, "sorted_desc", args.perturbation_seed)),
    ]
    perturbed_reports = []
    for variant_name, perturbed_dataset in perturbed_variants:
        variant_problem = clone_problem_with_dataset(base_problem, f"{dataset_name}_{variant_name}", perturbed_dataset)
        perturbed_reports.append(
            {
                "variant_name": variant_name,
                **analyze_dataset(
                    variant_problem,
                    candidate_modules,
                    f"{dataset_name}_{variant_name}",
                    perturbed_dataset,
                    args.trace_steps,
                    tie_score_epsilon,
                ),
            }
        )

    report = {
        "generated_at_utc": utc_now_iso(),
        "run_dir": run_dir,
        "dataset_name": dataset_name,
        "candidate_discovery": {
            "used_behavior_cards": discovery["cards_present"],
            "used_candidate_attempts": discovery["attempts_present"],
            "used_response_files": discovery["responses_present"],
            "candidate_record_count": len(candidate_records),
            "candidate_sources": sorted({record.get("source") for record in candidate_records}),
        },
        "analyzed_candidate_count": len(candidate_modules),
        "requested_max_candidates": args.max_candidates,
        "trace_steps": args.trace_steps,
        "embedded_report": embedded_report,
        "leave_one_out_report": leave_one_out_report,
        "perturbed_reports": perturbed_reports,
        "attribution": attribution_verdict(embedded_report, perturbed_reports),
        "reconstruction_failures": reconstruction_failures,
        "notes": [
            "No external alternative benchmark set is bundled in this script; alternative sensitivity is tested using deterministic perturbations of the embedded 5 instances.",
            "The report distinguishes full-instance used-bin vector diversity from per-instance behavior signatures.",
        ],
    }
    report = sanitize_json_value(report)

    with open(json_output_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False, allow_nan=False)
    with open(md_output_path, "w", encoding="utf-8") as file:
        file.write(markdown_summary(report))

    print(json.dumps(report["attribution"], indent=2, ensure_ascii=False))
    print(f"Saved JSON report to {json_output_path}")
    print(f"Saved Markdown summary to {md_output_path}")


if __name__ == "__main__":
    main()
