import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter

import yaml


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EOH_SRC = os.path.join(REPO_ROOT, "eoh", "src")
if EOH_SRC not in sys.path:
    sys.path.insert(0, EOH_SRC)

from eoh import eoh
from eoh.utils.getParas import Paras


def resolve_repo_path(path_value):
    if path_value is None:
        return None
    if os.path.isabs(path_value):
        return os.path.abspath(path_value)
    return os.path.abspath(os.path.join(REPO_ROOT, path_value))


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def resolve_llm_settings(llm_config, strict=True):
    use_local = bool(llm_config.get("use_local", False))
    settings = {
        "llm_use_local": use_local,
        "llm_local_url": os.environ.get("EOH_LLM_LOCAL_URL", llm_config.get("local_url")),
        "llm_api_endpoint": os.environ.get("EOH_LLM_API_ENDPOINT", llm_config.get("api_endpoint")),
        "llm_api_key": os.environ.get("EOH_LLM_API_KEY", llm_config.get("api_key")),
        "llm_model": os.environ.get("EOH_LLM_MODEL", llm_config.get("model")),
    }

    if strict and not use_local:
        unresolved = []
        for field in ["llm_api_endpoint", "llm_api_key", "llm_model"]:
            value = settings[field]
            if value in [None, "", "REQUIRED_BEFORE_RUN"]:
                unresolved.append(field)
        if unresolved:
            raise ValueError(
                "Missing required remote LLM settings: "
                + ", ".join(unresolved)
                + ". Set them in the config or via EOH_LLM_* environment variables."
            )

    return settings


def build_paras(config, config_path, strict_llm=True):
    baseline = config.get("baseline", {})
    problem = config.get("problem", {})
    search = config.get("search", {})
    evaluation = config.get("evaluation", {})
    artifacts = config.get("artifacts", {})
    reproducibility = config.get("reproducibility", {})
    behavior = config.get("behavior", {})

    llm_settings = resolve_llm_settings(config.get("llm", {}), strict=strict_llm)

    paras = Paras()
    paras.set_paras(
        method=search.get("method"),
        problem=problem.get("name"),
        selection=search.get("selection"),
        management=search.get("management"),
        ec_pop_size=search.get("population_size"),
        ec_n_pop=search.get("n_populations"),
        ec_m=search.get("n_parents_e1_e2"),
        ec_operators=search.get("operators"),
        ec_operator_weights=search.get("operator_weights"),
        exp_n_proc=search.get("parallel_workers"),
        exp_debug_mode=search.get("debug_mode", False),
        exp_output_path=resolve_repo_path(artifacts.get("output_root", ".")),
        exp_seed=reproducibility.get("global_seed"),
        exp_python_seed=reproducibility.get("python_seed"),
        exp_numpy_seed=reproducibility.get("numpy_seed"),
        exp_worker_seed=reproducibility.get("worker_seed_base"),
        **llm_settings,
    )

    if "timeout_seconds" in evaluation:
        paras.eva_timeout = evaluation["timeout_seconds"]
    if "use_numba_decorator" in evaluation:
        paras.eva_numba_decorator = evaluation["use_numba_decorator"]

    paras.exp_baseline_name = baseline.get("name")
    paras.exp_config_path = os.path.abspath(config_path)
    paras.exp_problem_name = problem.get("name")
    paras.exp_posthoc_eval_script = resolve_repo_path(problem.get("posthoc_eval_script"))
    paras.exp_search_evaluator = resolve_repo_path(problem.get("search_evaluator"))
    paras.exp_search_dataset_source = resolve_repo_path(problem.get("search_dataset_source"))
    paras.exp_prompts_path = resolve_repo_path(problem.get("prompts"))
    paras.exp_seed_policy = reproducibility.get("mode")
    paras.exp_worker_seed_strategy = reproducibility.get("worker_seed_strategy")
    paras.exp_behavior_enabled = behavior.get("enabled", False)
    paras.exp_behavior_config_path = resolve_repo_path(behavior.get("config_path"))
    paras.exp_behavior_system_id = behavior.get("system_id")
    return paras


def copy_config_snapshot(config_path, run_dir):
    destination = os.path.join(run_dir, "config_snapshot.yaml")
    shutil.copyfile(config_path, destination)
    return destination


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def append_run_summary(run_summary_path, update_payload):
    summary = load_json(run_summary_path)
    summary.update(update_payload)
    write_json(run_summary_path, summary)


def summarize_operator_usage(candidate_attempts_path):
    total = Counter()
    valid = Counter()
    invalid = Counter()

    if not os.path.exists(candidate_attempts_path):
        return {
            "total": {},
            "valid": {},
            "invalid": {},
        }

    with open(candidate_attempts_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
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


def get_problem_name_from_eval_script(eval_script_path):
    return os.path.basename(os.path.dirname(os.path.dirname(eval_script_path)))


def prepare_eval_workspace(eval_script_path, run_dir, best_code):
    problem_name = get_problem_name_from_eval_script(eval_script_path)
    source_dir = os.path.dirname(eval_script_path)
    workspace_dir = os.path.join(run_dir, "posthoc_eval", problem_name, "workspace")

    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)

    shutil.copytree(
        source_dir,
        workspace_dir,
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    heuristic_path = os.path.join(workspace_dir, "heuristic.py")
    with open(heuristic_path, "w", encoding="utf-8") as file:
        file.write(best_code.rstrip())
        file.write("\n")

    return workspace_dir


def run_posthoc_eval(eval_script_path, run_dir, best_code):
    workspace_dir = prepare_eval_workspace(eval_script_path, run_dir, best_code)
    env = os.environ.copy()
    env["EOH_RUN_DIR"] = run_dir

    completed = subprocess.run(
        [sys.executable, os.path.basename(eval_script_path)],
        cwd=workspace_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    log_dir = os.path.join(run_dir, "posthoc_eval", get_problem_name_from_eval_script(eval_script_path))
    stdout_path = os.path.join(log_dir, "stdout.txt")
    stderr_path = os.path.join(log_dir, "stderr.txt")
    with open(stdout_path, "w", encoding="utf-8") as file:
        file.write(completed.stdout)
    with open(stderr_path, "w", encoding="utf-8") as file:
        file.write(completed.stderr)

    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "workspace_dir": workspace_dir,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "eval_script": eval_script_path,
    }


def validate_problem_support(problem_name, eval_script_path):
    if problem_name not in ["bp_online", "tsp_construct"]:
        raise ValueError(f"Unsupported problem for run_baseline.py: {problem_name}")
    if not eval_script_path or not os.path.exists(eval_script_path):
        raise ValueError(f"Post-hoc evaluation script not found: {eval_script_path}")


def main():
    parser = argparse.ArgumentParser(description="Run the thesis baseline fork of EOH from a versioned config.")
    parser.add_argument(
        "--config",
        default=os.path.join(REPO_ROOT, "configs", "baseline_bp_online.yaml"),
        help="Path to the baseline YAML config file.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Load and validate config and paths without launching search.",
    )
    parser.add_argument(
        "--skip-posthoc",
        action="store_true",
        help="Skip the post-hoc evaluation phase after search.",
    )
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    config = load_config(config_path)
    paras = build_paras(config, config_path, strict_llm=not args.validate_only)
    validate_problem_support(paras.exp_problem_name, paras.exp_posthoc_eval_script)

    if args.validate_only:
        print(json.dumps(
            {
                "config_path": config_path,
                "problem": paras.exp_problem_name,
                "posthoc_eval_script": paras.exp_posthoc_eval_script,
                "search_evaluator": paras.exp_search_evaluator,
                "search_dataset_source": paras.exp_search_dataset_source,
                "prompts_path": paras.exp_prompts_path,
                "output_root": paras.exp_output_path,
                "llm_use_local": paras.llm_use_local,
                "llm_api_endpoint": paras.llm_api_endpoint,
                "llm_model": paras.llm_model,
                "behavior_enabled": paras.exp_behavior_enabled,
                "behavior_config_path": paras.exp_behavior_config_path,
            },
            indent=2,
        ))
        return

    evolution = eoh.EVOL(paras)
    paras.exp_config_snapshot_path = copy_config_snapshot(config_path, paras.exp_run_dir)

    evolution.run()

    run_summary_path = evolution.logger.run_summary_path
    operator_usage = summarize_operator_usage(evolution.logger.candidate_attempts_path)
    append_run_summary(
        run_summary_path,
        {
            "baseline_name": paras.exp_baseline_name,
            "config_path": paras.exp_config_path,
            "config_snapshot_path": paras.exp_config_snapshot_path,
            "operator_usage_summary": operator_usage,
        },
    )

    if args.skip_posthoc:
        append_run_summary(
            run_summary_path,
            {
                "posthoc_eval": {
                    "status": "skipped",
                    "reason": "--skip-posthoc",
                }
            },
        )
        return

    run_summary = load_json(run_summary_path)
    best_code = run_summary.get("best_code")
    if not best_code:
        append_run_summary(
            run_summary_path,
            {
                "posthoc_eval": {
                    "status": "failed",
                    "reason": "best_code_missing_from_run_summary",
                }
            },
        )
        raise RuntimeError("Post-hoc evaluation could not start because best_code was not available.")

    posthoc_result = run_posthoc_eval(paras.exp_posthoc_eval_script, paras.exp_run_dir, best_code)
    append_run_summary(run_summary_path, {"posthoc_eval": posthoc_result})

    if posthoc_result["status"] != "ok":
        raise RuntimeError(
            "Post-hoc evaluation failed. See "
            + posthoc_result["stdout_path"]
            + " and "
            + posthoc_result["stderr_path"]
        )


if __name__ == "__main__":
    main()
