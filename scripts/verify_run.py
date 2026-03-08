import argparse
import json
import os
import sys
from collections import Counter


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


REQUIRED_MANIFEST_KEYS = {
    "run_id",
    "started_at_utc",
    "base_output_path",
    "run_dir",
    "cwd",
    "python_version",
    "platform",
    "argv",
    "git",
    "paths",
    "paras",
    "problem_class",
    "method_class",
}

REQUIRED_SUMMARY_KEYS = {
    "run_id",
    "ended_at_utc",
    "elapsed_seconds",
    "logger_stats",
    "problem_class",
    "method_class",
    "results_dir",
    "final_population_size",
    "best_objective",
    "best_code",
    "best_algorithm",
    "saved_generation_files",
    "saved_best_files",
    "seed_summary",
    "baseline_name",
    "config_path",
    "config_snapshot_path",
    "operator_usage_summary",
}

REQUIRED_LOGGER_STATS_KEYS = {
    "candidate_attempts",
    "valid_candidates",
    "invalid_candidates",
    "llm_requests",
    "llm_retry_responses",
}

REQUIRED_ATTEMPT_KEYS = {
    "attempt_id",
    "operator",
    "population_index",
    "operator_index",
    "operator_count",
    "task_index",
    "pop_size",
    "parent_count_requested",
    "timeout_seconds",
    "used_numba",
    "worker_seed_attempt",
    "worker_seed_evaluation",
    "status",
    "error_type",
    "error_message",
    "objective",
    "code_sha256",
    "algorithm_sha256",
    "raw_code_sha256",
    "evaluation_code_sha256",
    "parents",
    "llm_trace_files",
    "elapsed_seconds",
    "logged_at_utc",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}: {exc}") from exc
    return records


def latest_run_dir(base_runs_dir):
    if not os.path.isdir(base_runs_dir):
        raise FileNotFoundError(f"Runs directory not found: {base_runs_dir}")
    run_dirs = [
        os.path.join(base_runs_dir, name)
        for name in os.listdir(base_runs_dir)
        if os.path.isdir(os.path.join(base_runs_dir, name))
    ]
    if not run_dirs:
        raise FileNotFoundError(f"No run directories found in {base_runs_dir}")
    return max(run_dirs, key=os.path.getmtime)


def require_keys(record, required_keys, label, errors):
    missing = sorted(required_keys - set(record.keys()))
    if missing:
        errors.append(f"{label} missing keys: {missing}")


def check_path_exists(path, label, errors):
    if not os.path.exists(path):
        errors.append(f"{label} missing: {path}")


def summarize_attempts(records):
    total = Counter()
    valid = Counter()
    invalid = Counter()
    for record in records:
        operator = record.get("operator") or "unknown"
        total[operator] += 1
        if record.get("status") == "valid":
            valid[operator] += 1
        else:
            invalid[operator] += 1
    return {
        "total": dict(sorted(total.items())),
        "valid": dict(sorted(valid.items())),
        "invalid": dict(sorted(invalid.items())),
    }


def verify_attempt_record(record, run_dir, errors):
    require_keys(record, REQUIRED_ATTEMPT_KEYS, f"candidate_attempt[{record.get('attempt_id', '?')}]", errors)

    status = record.get("status")
    if status not in ["valid", "invalid"]:
        errors.append(f"candidate_attempt[{record.get('attempt_id')}] has unexpected status: {status}")

    if record.get("elapsed_seconds") is None:
        errors.append(f"candidate_attempt[{record.get('attempt_id')}] missing elapsed_seconds")

    if status == "valid":
        if record.get("objective") is None:
            errors.append(f"candidate_attempt[{record.get('attempt_id')}] is valid but objective is None")
        if record.get("code_sha256") is None:
            errors.append(f"candidate_attempt[{record.get('attempt_id')}] is valid but code_sha256 is None")
    else:
        if record.get("objective") is not None:
            errors.append(f"candidate_attempt[{record.get('attempt_id')}] is invalid but objective is not None")

    trace = record.get("llm_trace_files")
    if trace is None:
        errors.append(f"candidate_attempt[{record.get('attempt_id')}] missing llm_trace_files")
        return

    trace_required = {
        "request_id",
        "prompt_file",
        "prompt_sha256",
        "response_files",
        "response_sha256",
        "response_count",
        "parse_success",
        "parse_error",
        "parse_retry_count",
    }
    require_keys(trace, trace_required, f"llm_trace_files[{record.get('attempt_id', '?')}]", errors)

    prompt_file = trace.get("prompt_file")
    if prompt_file is None:
        errors.append(f"candidate_attempt[{record.get('attempt_id')}] prompt_file is None")
    else:
        check_path_exists(prompt_file, f"prompt_file for {record.get('attempt_id')}", errors)

    response_files = trace.get("response_files") or []
    response_sha256 = trace.get("response_sha256") or []
    response_count = trace.get("response_count")
    if response_count != len(response_files):
        errors.append(
            f"candidate_attempt[{record.get('attempt_id')}] response_count mismatch: "
            f"{response_count} vs {len(response_files)}"
        )
    if response_count != len(response_sha256):
        errors.append(
            f"candidate_attempt[{record.get('attempt_id')}] response_sha256 count mismatch: "
            f"{response_count} vs {len(response_sha256)}"
        )
    for response_file in response_files:
        check_path_exists(response_file, f"response_file for {record.get('attempt_id')}", errors)


def verify_run(run_dir, expect_posthoc=False):
    errors = []
    run_dir = os.path.abspath(run_dir)

    manifest_path = os.path.join(run_dir, "run_manifest.json")
    summary_path = os.path.join(run_dir, "run_summary.json")
    config_snapshot_path = os.path.join(run_dir, "config_snapshot.yaml")
    candidate_attempts_path = os.path.join(run_dir, "logs", "candidate_attempts.jsonl")
    invalid_candidates_path = os.path.join(run_dir, "logs", "invalid_candidates.jsonl")
    prompts_dir = os.path.join(run_dir, "logs", "prompts")
    responses_dir = os.path.join(run_dir, "logs", "responses")
    pops_dir = os.path.join(run_dir, "results", "pops")
    pops_best_dir = os.path.join(run_dir, "results", "pops_best")

    for label, path in [
        ("run_manifest", manifest_path),
        ("run_summary", summary_path),
        ("config_snapshot", config_snapshot_path),
        ("candidate_attempts", candidate_attempts_path),
        ("invalid_candidates", invalid_candidates_path),
        ("prompts_dir", prompts_dir),
        ("responses_dir", responses_dir),
        ("results/pops", pops_dir),
        ("results/pops_best", pops_best_dir),
    ]:
        check_path_exists(path, label, errors)

    if errors:
        return errors, None

    manifest = load_json(manifest_path)
    summary = load_json(summary_path)
    attempts = load_jsonl(candidate_attempts_path)
    invalid_attempts = load_jsonl(invalid_candidates_path)

    require_keys(manifest, REQUIRED_MANIFEST_KEYS, "run_manifest", errors)
    require_keys(summary, REQUIRED_SUMMARY_KEYS, "run_summary", errors)
    require_keys(summary.get("logger_stats", {}), REQUIRED_LOGGER_STATS_KEYS, "run_summary.logger_stats", errors)

    if manifest.get("run_id") != os.path.basename(run_dir):
        errors.append(
            f"run_manifest run_id mismatch: {manifest.get('run_id')} vs directory {os.path.basename(run_dir)}"
        )
    if summary.get("run_id") != manifest.get("run_id"):
        errors.append("run_summary run_id does not match run_manifest run_id")
    if manifest.get("run_dir") != run_dir:
        errors.append(f"run_manifest run_dir mismatch: {manifest.get('run_dir')} vs {run_dir}")

    paras = manifest.get("paras", {})
    if paras.get("llm_api_key") not in [None, "", "<redacted>"]:
        errors.append("run_manifest paras.llm_api_key is not redacted")

    if not attempts:
        errors.append("candidate_attempts.jsonl is empty")

    attempt_ids = set()
    invalid_attempt_ids = set()
    valid_count = 0
    invalid_count = 0
    for record in attempts:
        attempt_id = record.get("attempt_id")
        if attempt_id in attempt_ids:
            errors.append(f"duplicate attempt_id in candidate_attempts.jsonl: {attempt_id}")
        attempt_ids.add(attempt_id)
        verify_attempt_record(record, run_dir, errors)
        if record.get("status") == "valid":
            valid_count += 1
        else:
            invalid_count += 1

    for record in invalid_attempts:
        attempt_id = record.get("attempt_id")
        invalid_attempt_ids.add(attempt_id)
        if record.get("status") == "valid":
            errors.append(f"invalid_candidates.jsonl contains valid attempt: {attempt_id}")

    expected_invalid_ids = {record.get("attempt_id") for record in attempts if record.get("status") != "valid"}
    if invalid_attempt_ids != expected_invalid_ids:
        errors.append("invalid_candidates.jsonl attempt IDs do not match invalid attempts from candidate_attempts.jsonl")

    logger_stats = summary.get("logger_stats", {})
    if logger_stats.get("candidate_attempts") != len(attempts):
        errors.append(
            f"logger_stats candidate_attempts mismatch: {logger_stats.get('candidate_attempts')} vs {len(attempts)}"
        )
    if logger_stats.get("valid_candidates") != valid_count:
        errors.append(
            f"logger_stats valid_candidates mismatch: {logger_stats.get('valid_candidates')} vs {valid_count}"
        )
    if logger_stats.get("invalid_candidates") != invalid_count:
        errors.append(
            f"logger_stats invalid_candidates mismatch: {logger_stats.get('invalid_candidates')} vs {invalid_count}"
        )

    computed_operator_usage = summarize_attempts(attempts)
    if summary.get("operator_usage_summary") != computed_operator_usage:
        errors.append("operator_usage_summary does not match candidate_attempts.jsonl")

    saved_generation_files = summary.get("saved_generation_files") or []
    saved_best_files = summary.get("saved_best_files") or []
    if not saved_generation_files:
        errors.append("run_summary saved_generation_files is empty")
    if not saved_best_files:
        errors.append("run_summary saved_best_files is empty")
    for path in saved_generation_files + saved_best_files:
        check_path_exists(path, "saved population artifact", errors)

    if summary.get("best_code") is None:
        errors.append("run_summary best_code is None")
    if summary.get("best_algorithm") is None:
        errors.append("run_summary best_algorithm is None")
    if summary.get("best_objective") is None:
        errors.append("run_summary best_objective is None")

    posthoc = summary.get("posthoc_eval")
    if expect_posthoc:
        if not isinstance(posthoc, dict):
            errors.append("posthoc_eval missing from run_summary")
        else:
            if posthoc.get("status") != "ok":
                errors.append(f"posthoc_eval status is not ok: {posthoc.get('status')}")
            for key in ["stdout_path", "stderr_path"]:
                path = posthoc.get(key)
                if not path:
                    errors.append(f"posthoc_eval missing {key}")
                else:
                    check_path_exists(path, f"posthoc_eval {key}", errors)

    result = {
        "run_dir": run_dir,
        "run_id": summary.get("run_id"),
        "candidate_attempt_count": len(attempts),
        "invalid_candidate_count": len(invalid_attempts),
        "valid_candidate_count": valid_count,
        "operator_usage_summary": computed_operator_usage,
        "posthoc_status": None if not isinstance(posthoc, dict) else posthoc.get("status"),
    }
    return errors, result


def main():
    parser = argparse.ArgumentParser(description="Verify that a completed S0 run folder contains complete artifacts and expected schema.")
    parser.add_argument(
        "--run-dir",
        help="Path to a specific run directory. If omitted, the latest directory under ./runs is used.",
    )
    parser.add_argument(
        "--expect-posthoc",
        action="store_true",
        help="Require successful post-hoc evaluation artifacts in the run summary and on disk.",
    )
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir) if args.run_dir else latest_run_dir(os.path.join(REPO_ROOT, "runs"))
    errors, result = verify_run(run_dir, expect_posthoc=args.expect_posthoc)

    payload = {
        "ok": len(errors) == 0,
        "run_dir": run_dir,
        "errors": errors,
        "result": result,
    }
    print(json.dumps(payload, indent=2))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
