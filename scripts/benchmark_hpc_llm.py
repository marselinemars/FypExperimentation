import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
import yaml


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EOH_SRC = os.path.join(REPO_ROOT, "eoh", "src")
if EOH_SRC not in sys.path:
    sys.path.insert(0, EOH_SRC)

from eoh.problems.optimization.bp_online.prompts import GetPrompts


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def build_bp_i1_prompt():
    prompts = GetPrompts()
    prompt_task = prompts.get_task()
    prompt_func_name = prompts.get_func_name()
    prompt_func_inputs = prompts.get_func_inputs()
    prompt_func_outputs = prompts.get_func_outputs()
    prompt_inout_inf = prompts.get_inout_inf()
    prompt_other_inf = prompts.get_other_inf()

    if len(prompt_func_inputs) > 1:
        joined_inputs = ", ".join("'" + s + "'" for s in prompt_func_inputs)
    else:
        joined_inputs = "'" + prompt_func_inputs[0] + "'"

    if len(prompt_func_outputs) > 1:
        joined_outputs = ", ".join("'" + s + "'" for s in prompt_func_outputs)
    else:
        joined_outputs = "'" + prompt_func_outputs[0] + "'"

    prompt_content = (
        prompt_task
        + "\n"
        + "First, describe your new algorithm and main steps in one sentence. "
        + "The description must be inside a brace. Next, implement it in Python as a function named "
        + prompt_func_name
        + ". This function should accept "
        + str(len(prompt_func_inputs))
        + " input(s): "
        + joined_inputs
        + ". The function should return "
        + str(len(prompt_func_outputs))
        + " output(s): "
        + joined_outputs
        + ". "
        + prompt_inout_inf
        + " "
        + prompt_other_inf
        + "\n"
        + "Do not give additional explanations."
    )
    return prompt_content


def build_prompt_suite():
    short_prompt = "1+1=?"
    medium_prompt = (
        "Write a Python function named score(item, bins) that returns a NumPy array of scores for feasible bins. "
        "The goal is to minimize the number of used bins in online bin packing. "
        "Return only a short valid Python function."
    )
    eoh_i1_prompt = build_bp_i1_prompt()
    return [
        {"name": "short_ping", "content": short_prompt},
        {"name": "medium_binpacking", "content": medium_prompt},
        {"name": "eoh_i1_bp_online", "content": eoh_i1_prompt},
    ]


def endpoint_join(base, suffix):
    return base.rstrip("/") + suffix


def fetch_models(base_url, api_key, timeout_seconds):
    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.perf_counter()
    response = requests.get(endpoint_join(base_url, "/models"), headers=headers, timeout=timeout_seconds)
    elapsed = time.perf_counter() - started
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = {"raw_text": response.text[:2000]}
    return {
        "ok": response.ok,
        "status_code": response.status_code,
        "elapsed_seconds": round(elapsed, 6),
        "payload": payload,
    }


def send_chat_completion(base_url, api_key, model, prompt, timeout_seconds, request_label):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    started = time.perf_counter()
    try:
        response = requests.post(
            endpoint_join(base_url, "/chat/completions"),
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
        elapsed = time.perf_counter() - started
        raw_json = None
        raw_text = None
        content = None
        error_message = None
        try:
            raw_json = response.json()
            content = raw_json["choices"][0]["message"]["content"]
        except Exception as exc:
            raw_text = response.text[:4000]
            error_message = str(exc)

        return {
            "request_label": request_label,
            "ok": response.ok and content is not None,
            "status_code": response.status_code,
            "elapsed_seconds": round(elapsed, 6),
            "response_text_preview": None if content is None else content[:200],
            "response_text_length": None if content is None else len(content),
            "error_message": error_message,
            "raw_text_preview": raw_text,
        }
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "request_label": request_label,
            "ok": False,
            "status_code": None,
            "elapsed_seconds": round(elapsed, 6),
            "response_text_preview": None,
            "response_text_length": None,
            "error_message": repr(exc),
            "raw_text_preview": None,
        }


def run_prompt_benchmark(base_url, api_key, model, prompt_name, prompt_content, concurrency, repeats, timeout_seconds):
    records = []
    for repeat_index in range(1, repeats + 1):
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for worker_index in range(1, concurrency + 1):
                request_label = f"{prompt_name}__c{concurrency}__r{repeat_index}__w{worker_index}"
                futures.append(
                    executor.submit(
                        send_chat_completion,
                        base_url,
                        api_key,
                        model,
                        prompt_content,
                        timeout_seconds,
                        request_label,
                    )
                )
            for future in as_completed(futures):
                record = future.result()
                record["prompt_name"] = prompt_name
                record["concurrency"] = concurrency
                record["repeat"] = repeat_index
                record["prompt_length"] = len(prompt_content)
                records.append(record)

    latencies = [record["elapsed_seconds"] for record in records]
    success_count = sum(1 for record in records if record["ok"])
    failure_count = len(records) - success_count
    status_counts = {}
    for record in records:
        key = str(record["status_code"])
        status_counts[key] = status_counts.get(key, 0) + 1

    return {
        "prompt_name": prompt_name,
        "prompt_length": len(prompt_content),
        "concurrency": concurrency,
        "repeats": repeats,
        "request_count": len(records),
        "success_count": success_count,
        "failure_count": failure_count,
        "mean_latency_seconds": round(statistics.mean(latencies), 6) if latencies else None,
        "median_latency_seconds": round(statistics.median(latencies), 6) if latencies else None,
        "max_latency_seconds": round(max(latencies), 6) if latencies else None,
        "status_counts": status_counts,
        "records": records,
    }


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Benchmark the HPC LLM endpoint for latency and concurrency before freezing runtime settings.")
    parser.add_argument(
        "--config",
        default=os.path.join(REPO_ROOT, "configs", "baseline_bp_online.yaml"),
        help="Config file used to read endpoint and model.",
    )
    parser.add_argument(
        "--concurrency",
        default="1,2,4",
        help="Comma-separated concurrency levels to test.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of repeated batches per concurrency level.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=240,
        help="HTTP timeout for each benchmark request.",
    )
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    config = load_config(config_path)
    llm_config = config.get("llm", {})
    base_url = os.environ.get("EOH_LLM_API_ENDPOINT", llm_config.get("api_endpoint"))
    api_key = os.environ.get("EOH_LLM_API_KEY", llm_config.get("api_key"))
    model = os.environ.get("EOH_LLM_MODEL", llm_config.get("model"))

    if not base_url or base_url == "REQUIRED_BEFORE_RUN":
        raise ValueError("Missing LLM endpoint. Set it in the config or via EOH_LLM_API_ENDPOINT.")
    if not api_key or api_key == "SET_VIA_ENV_EOH_LLM_API_KEY":
        raise ValueError("Missing LLM API key. Set EOH_LLM_API_KEY in the environment.")
    if not model or model == "REQUIRED_BEFORE_RUN":
        raise ValueError("Missing model name. Set it in the config or via EOH_LLM_MODEL.")

    concurrencies = [int(value.strip()) for value in args.concurrency.split(",") if value.strip()]
    prompt_suite = build_prompt_suite()

    benchmark_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(REPO_ROOT, "benchmark_results", benchmark_id)
    output_path = os.path.join(output_dir, "hpc_llm_benchmark.json")

    result = {
        "benchmark_id": benchmark_id,
        "started_at_utc": utc_now(),
        "config_path": config_path,
        "endpoint": base_url,
        "model": model,
        "concurrency_levels": concurrencies,
        "repeats": args.repeats,
        "timeout_seconds": args.timeout_seconds,
        "models_check": fetch_models(base_url, api_key, args.timeout_seconds),
        "prompt_benchmarks": [],
    }

    for prompt_item in prompt_suite:
        print(f"Benchmarking prompt={prompt_item['name']} length={len(prompt_item['content'])}")
        for concurrency in concurrencies:
            print(f"  concurrency={concurrency} repeats={args.repeats}")
            benchmark = run_prompt_benchmark(
                base_url,
                api_key,
                model,
                prompt_item["name"],
                prompt_item["content"],
                concurrency,
                args.repeats,
                args.timeout_seconds,
            )
            result["prompt_benchmarks"].append(benchmark)
            print(
                f"    success={benchmark['success_count']}/{benchmark['request_count']} "
                f"mean={benchmark['mean_latency_seconds']}s max={benchmark['max_latency_seconds']}s"
            )

    result["ended_at_utc"] = utc_now()
    write_json(output_path, result)

    summary = {
        "benchmark_id": benchmark_id,
        "output_path": output_path,
        "models_check_ok": result["models_check"]["ok"],
        "prompt_summaries": [
            {
                "prompt_name": item["prompt_name"],
                "concurrency": item["concurrency"],
                "success_count": item["success_count"],
                "request_count": item["request_count"],
                "mean_latency_seconds": item["mean_latency_seconds"],
                "max_latency_seconds": item["max_latency_seconds"],
            }
            for item in result["prompt_benchmarks"]
        ],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
