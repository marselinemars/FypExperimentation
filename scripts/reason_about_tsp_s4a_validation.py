import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EOH_SRC_ROOT = os.path.join(REPO_ROOT, "eoh", "src")
for candidate_path in [REPO_ROOT, EOH_SRC_ROOT]:
    if candidate_path not in sys.path:
        sys.path.insert(0, candidate_path)

from eoh.llm.api_general import InterfaceAPI
from summarize_tsp_s4a_validation import (
    build_generation_rows,
    build_threshold_stability,
    discover_behavior_artifacts,
    is_tsp_card,
    is_tsp_summary,
    latest_run_dirs,
    summarize_label_frequencies,
)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(text)


def resolve_run_dirs(explicit_run_dirs, latest_count):
    if explicit_run_dirs:
        return [os.path.abspath(path) for path in explicit_run_dirs]
    runs_root = os.path.join(REPO_ROOT, "runs")
    latest = latest_count or 3
    return latest_run_dirs(runs_root, latest)


def build_aggregate_report(run_dirs):
    all_cards = []
    all_summaries = []
    for run_dir in run_dirs:
        cards, summaries = discover_behavior_artifacts(run_dir)
        all_cards.extend([card for card in cards if is_tsp_card(card)])
        all_summaries.extend([summary for summary in summaries if is_tsp_summary(summary)])

    return {
        "generated_at_utc": utc_now_iso(),
        "run_dirs": run_dirs,
        "diagnosis_frequency": summarize_label_frequencies(all_cards),
        "generation_metrics": build_generation_rows(all_summaries),
        "threshold_stability": build_threshold_stability(all_cards),
    }


def _compact_generation_rows(rows, limit=12):
    compact = []
    for row in rows[:limit]:
        compact.append(
            {
                "run_id": row.get("run_id"),
                "generation": row.get("generation"),
                "valid_candidate_count": row.get("valid_candidate_count"),
                "objective_duplicate_ratio": row.get("objective_duplicate_ratio"),
                "behavior_duplicate_ratio": row.get("behavior_duplicate_ratio"),
                "unique_behavior_signature_count": row.get("unique_behavior_signature_count"),
                "mean_nearest_neighbor_pick_rate": row.get("mean_nearest_neighbor_pick_rate"),
                "mean_chosen_rank_ratio": row.get("mean_chosen_rank_ratio"),
                "mean_rank_bucket_entropy": row.get("mean_rank_bucket_entropy"),
            }
        )
    return compact


def build_reasoning_prompt(report):
    compact_report = {
        "run_count": len(report.get("run_dirs") or []),
        "diagnosis_frequency": report.get("diagnosis_frequency") or {},
        "generation_metrics": _compact_generation_rows(report.get("generation_metrics") or []),
        "threshold_stability": report.get("threshold_stability") or {},
    }

    schema = {
        "summary": "short paragraph",
        "observations": ["list of concise evidence-backed observations"],
        "diagnosis": {
            "likely_failure_mode": "single best explanation",
            "secondary_hypotheses": ["optional alternative explanations"],
            "confidence": "low|medium|high",
            "evidence": ["specific metrics from the input"]
        },
        "recommended_actions": [
            {
                "priority": 1,
                "action": "specific next step",
                "why": "why this action follows from the evidence",
                "expected_signal": "what result would confirm or reject the hypothesis"
            }
        ],
        "threshold_review": [
            {
                "label": "diagnosis label name",
                "status": "keep|watch|recalibrate|remove",
                "reason": "brief rationale grounded in the metrics"
            }
        ],
        "questions_to_answer_next": ["short follow-up questions for the next experiment"]
    }

    return (
        "You are helping interpret TSP S4a diagnostic aggregates from an evolutionary heuristic search system.\n"
        "Your job is to reason over the diagnostics and propose the next actions.\n"
        "Do not explain the whole system. Stay focused on what the metrics imply.\n"
        "Ground every claim in the provided evidence.\n"
        "Return strict JSON only. Do not wrap it in markdown fences.\n\n"
        "Important framing:\n"
        "- This is a representation-and-diagnosis phase, not an intervention phase.\n"
        "- behaviorally_duplicate should be judged for selectivity.\n"
        "- unstable_start_sensitive should be judged for whether it meaningfully separates candidates.\n"
        "- repetitive_ranking_pattern and edge_length_extreme_bias may be overactive and should be assessed critically.\n"
        "- Recommended actions should be concrete experimental next steps, not broad theory.\n\n"
        "Required JSON schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n\n"
        "Diagnostics input:\n"
        f"{json.dumps(compact_report, indent=2, ensure_ascii=False)}\n"
    )


def extract_json_payload(text):
    if not text:
        raise ValueError("Empty LLM response")

    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def resolve_api_settings():
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("API_KEY")
    api_endpoint = os.getenv("EOH_API_ENDPOINT")
    model = os.getenv("EOH_MODEL", "llama-3.3-70b-versatile")
    timeout = int(os.getenv("EOH_API_TIMEOUT", "250"))

    if not api_key:
        raise RuntimeError("Missing GROQ_API_KEY or API_KEY")
    if not api_endpoint:
        raise RuntimeError("Missing EOH_API_ENDPOINT")

    return {
        "api_key": api_key,
        "api_endpoint": api_endpoint,
        "model": model,
        "timeout": timeout,
    }


def build_markdown(report, llm_report):
    lines = []
    lines.append("# TSP S4a Diagnostic Reasoner")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at_utc']}`")
    lines.append(f"- Run count: `{len(report.get('run_dirs') or [])}`")
    lines.append(f"- Model: `{llm_report.get('model')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(llm_report["analysis"].get("summary", ""))
    lines.append("")
    lines.append("## Observations")
    lines.append("")
    for item in llm_report["analysis"].get("observations") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Diagnosis")
    lines.append("")
    diagnosis = llm_report["analysis"].get("diagnosis") or {}
    lines.append(f"- Likely failure mode: `{diagnosis.get('likely_failure_mode')}`")
    lines.append(f"- Confidence: `{diagnosis.get('confidence')}`")
    for item in diagnosis.get("evidence") or []:
        lines.append(f"- Evidence: {item}")
    for item in diagnosis.get("secondary_hypotheses") or []:
        lines.append(f"- Secondary hypothesis: {item}")
    lines.append("")
    lines.append("## Recommended Actions")
    lines.append("")
    for action in llm_report["analysis"].get("recommended_actions") or []:
        lines.append(
            f"- P{action.get('priority')}: {action.get('action')} "
            f"(why: {action.get('why')}; expected signal: {action.get('expected_signal')})"
        )
    lines.append("")
    lines.append("## Threshold Review")
    lines.append("")
    for review in llm_report["analysis"].get("threshold_review") or []:
        lines.append(
            f"- `{review.get('label')}` -> `{review.get('status')}`: {review.get('reason')}"
        )
    lines.append("")
    lines.append("## Questions To Answer Next")
    lines.append("")
    for item in llm_report["analysis"].get("questions_to_answer_next") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Use an LLM to reason over aggregated TSP S4a diagnostics and propose next actions.")
    parser.add_argument("--run-dir", action="append", dest="run_dirs", help="Run directory to include. Can be passed multiple times.")
    parser.add_argument("--latest", type=int, default=0, help="Use the latest N run directories under ./runs when --run-dir is not provided.")
    parser.add_argument("--report-json", help="Use an existing aggregate report JSON instead of rebuilding it.")
    parser.add_argument("--aggregate-output-json", help="Optional output path for the aggregate report JSON that feeds the reasoner.")
    parser.add_argument("--output-json", help="Optional output path for the LLM reasoner JSON.")
    parser.add_argument("--output-md", help="Optional output path for the LLM reasoner markdown.")
    parser.add_argument("--dry-run", action="store_true", help="Only build and save the aggregate report and prompt without calling the LLM.")
    args = parser.parse_args()

    if args.report_json:
        report = load_json(os.path.abspath(args.report_json))
    else:
        run_dirs = resolve_run_dirs(args.run_dirs, args.latest)
        report = build_aggregate_report(run_dirs)

    aggregate_output_json = (
        os.path.abspath(args.aggregate_output_json)
        if args.aggregate_output_json
        else os.path.join(REPO_ROOT, "analysis", "tsp_s4a_validation_report.json")
    )
    output_json = (
        os.path.abspath(args.output_json)
        if args.output_json
        else os.path.join(REPO_ROOT, "analysis", "tsp_s4a_reasoner_report.json")
    )
    output_md = (
        os.path.abspath(args.output_md)
        if args.output_md
        else os.path.join(REPO_ROOT, "analysis", "tsp_s4a_reasoner_report.md")
    )
    prompt_path = os.path.join(REPO_ROOT, "analysis", "tsp_s4a_reasoner_prompt.txt")
    raw_response_path = os.path.join(REPO_ROOT, "analysis", "tsp_s4a_reasoner_raw_response.txt")

    write_json(aggregate_output_json, report)

    prompt = build_reasoning_prompt(report)
    write_text(prompt_path, prompt)

    if args.dry_run:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nAggregate report written to: {aggregate_output_json}")
        print(f"Prompt written to: {prompt_path}")
        return

    settings = resolve_api_settings()
    client = InterfaceAPI(
        settings["api_endpoint"],
        settings["api_key"],
        settings["model"],
        debug_mode=False,
        timeout_seconds=settings["timeout"],
    )
    raw_response = client.get_response(prompt)
    write_text(raw_response_path, raw_response or "")

    analysis = extract_json_payload(raw_response)
    llm_report = {
        "generated_at_utc": utc_now_iso(),
        "model": settings["model"],
        "api_endpoint": settings["api_endpoint"],
        "source_report_path": aggregate_output_json,
        "analysis": analysis,
    }

    write_json(output_json, llm_report)
    write_text(output_md, build_markdown(report, llm_report))

    print(json.dumps(llm_report, indent=2, ensure_ascii=False))
    print(f"\nAggregate report written to: {aggregate_output_json}")
    print(f"Prompt written to: {prompt_path}")
    print(f"Raw response written to: {raw_response_path}")
    print(f"Reasoner JSON written to: {output_json}")
    print(f"Reasoner markdown written to: {output_md}")


if __name__ == "__main__":
    main()
