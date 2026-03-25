import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def latest_run_dirs(runs_root, count):
    run_dirs = [
        os.path.join(runs_root, name)
        for name in os.listdir(runs_root)
        if os.path.isdir(os.path.join(runs_root, name))
    ]
    run_dirs.sort(key=os.path.getmtime, reverse=True)
    return run_dirs[:count]


def discover_behavior_artifacts(run_dir):
    behavior_dir = os.path.join(run_dir, "behavior")
    cards_dir = os.path.join(behavior_dir, "cards")
    summaries_dir = os.path.join(behavior_dir, "generation_summaries")
    if not os.path.isdir(cards_dir) or not os.path.isdir(summaries_dir):
        raise FileNotFoundError(f"S4a behavior artifacts not found in {run_dir}")

    cards = []
    for name in sorted(os.listdir(cards_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(cards_dir, name)
        payload = load_json(path)
        payload["_card_path"] = path
        payload["_run_dir"] = run_dir
        payload["_run_id"] = payload["identity"]["run_id"]
        cards.append(payload)

    summaries = []
    for name in sorted(os.listdir(summaries_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(summaries_dir, name)
        payload = load_json(path)
        payload["_summary_path"] = path
        payload["_run_dir"] = run_dir
        payload["_run_id"] = os.path.basename(run_dir)
        summaries.append(payload)

    return cards, summaries


def is_tsp_card(card):
    return (card.get("identity") or {}).get("problem_type") == "tsp_construct"


def is_tsp_summary(summary):
    return summary.get("problem_type") == "tsp_construct"


def summarize_label_frequencies(cards):
    total_labels = Counter()
    valid_labels = Counter()
    primary_labels = Counter()

    for card in cards:
        diagnosis = card.get("diagnosis") or {}
        primary = diagnosis.get("primary_label")
        if primary:
            primary_labels[primary] += 1
        labels = diagnosis.get("labels") or []
        for label in labels:
            total_labels[label] += 1
            if (card.get("identity") or {}).get("valid"):
                valid_labels[label] += 1

    return {
        "all_cards": dict(sorted(total_labels.items())),
        "valid_cards_only": dict(sorted(valid_labels.items())),
        "primary_labels": dict(sorted(primary_labels.items())),
    }


def build_generation_rows(summaries):
    rows = []
    for summary in sorted(summaries, key=lambda item: (item["_run_id"], item.get("generation", -1))):
        rows.append(
            {
                "run_id": summary["_run_id"],
                "generation": summary.get("generation"),
                "candidate_count": summary.get("candidate_count"),
                "valid_candidate_count": summary.get("valid_candidate_count"),
                "invalid_candidate_count": summary.get("invalid_candidate_count"),
                "objective_duplicate_ratio": summary.get("objective_duplicate_ratio"),
                "behavior_duplicate_ratio": summary.get("behavior_duplicate_ratio"),
                "unique_behavior_signature_count": summary.get("number_of_unique_behavioral_signatures"),
                "mean_nearest_neighbor_pick_rate": summary.get("mean_nearest_neighbor_pick_rate"),
                "mean_chosen_rank_ratio": summary.get("mean_chosen_rank_ratio"),
                "mean_rank_bucket_entropy": summary.get("mean_rank_bucket_entropy"),
            }
        )
    return rows


def _mean(values):
    return (sum(values) / len(values)) if values else None


def _collect_valid_tsp_cards(cards):
    return [card for card in cards if (card.get("identity") or {}).get("valid")]


def inspect_behaviorally_duplicate(cards):
    valid_cards = _collect_valid_tsp_cards(cards)
    total_valid = len(valid_cards) or 1
    duplicate_cards = [card for card in valid_cards if (card.get("duplicates") or {}).get("is_behavior_duplicate")]
    by_generation = defaultdict(lambda: {"valid": 0, "duplicates": 0})
    for card in valid_cards:
        key = (card["_run_id"], (card.get("identity") or {}).get("generation"))
        by_generation[key]["valid"] += 1
        if (card.get("duplicates") or {}).get("is_behavior_duplicate"):
            by_generation[key]["duplicates"] += 1

    return {
        "valid_duplicate_frequency": len(duplicate_cards) / total_valid,
        "valid_duplicate_count": len(duplicate_cards),
        "valid_candidate_count": len(valid_cards),
        "per_generation_frequency": [
            {
                "run_id": run_id,
                "generation": generation,
                "behaviorally_duplicate_frequency": values["duplicates"] / values["valid"] if values["valid"] else None,
            }
            for (run_id, generation), values in sorted(by_generation.items())
        ],
        "assessment": "selective" if len(duplicate_cards) < total_valid else "non_selective",
    }


def inspect_unstable_start_sensitive(cards):
    valid_cards = _collect_valid_tsp_cards(cards)
    labeled = []
    unlabeled = []
    for card in valid_cards:
        labels = (card.get("diagnosis") or {}).get("labels") or []
        if "unstable_start_sensitive" in labels:
            labeled.append(card)
        else:
            unlabeled.append(card)

    def _average_objective(group):
        objectives = [(card.get("identity") or {}).get("objective") for card in group if (card.get("identity") or {}).get("objective") is not None]
        return _mean(objectives)

    def _average_alt_delta(group):
        deltas = [(card.get("robustness") or {}).get("alt_start_relative_score_delta") for card in group if (card.get("robustness") or {}).get("alt_start_relative_score_delta") is not None]
        return _mean(deltas)

    labeled_avg_obj = _average_objective(labeled)
    unlabeled_avg_obj = _average_objective(unlabeled)
    labeled_avg_delta = _average_alt_delta(labeled)
    unlabeled_avg_delta = _average_alt_delta(unlabeled)

    assessment = "inconclusive"
    if labeled and unlabeled and labeled_avg_delta is not None and unlabeled_avg_delta is not None:
        assessment = "meaningful_separator" if labeled_avg_delta > unlabeled_avg_delta else "weak_separator"

    return {
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "average_objective_labeled": labeled_avg_obj,
        "average_objective_unlabeled": unlabeled_avg_obj,
        "average_alt_start_delta_labeled": labeled_avg_delta,
        "average_alt_start_delta_unlabeled": unlabeled_avg_delta,
        "assessment": assessment,
    }


def inspect_overactive_label(cards, label):
    valid_cards = _collect_valid_tsp_cards(cards)
    total_valid = len(valid_cards) or 1
    labeled = [card for card in valid_cards if label in ((card.get("diagnosis") or {}).get("labels") or [])]
    frequency = len(labeled) / total_valid
    if frequency >= 0.8:
        assessment = "overactive"
    elif frequency <= 0.3:
        assessment = "selective"
    else:
        assessment = "moderate"
    return {
        "label": label,
        "count": len(labeled),
        "valid_candidate_count": len(valid_cards),
        "frequency": frequency,
        "assessment": assessment,
    }


def build_threshold_stability(cards):
    return {
        "behaviorally_duplicate": inspect_behaviorally_duplicate(cards),
        "unstable_start_sensitive": inspect_unstable_start_sensitive(cards),
        "repetitive_ranking_pattern": inspect_overactive_label(cards, "repetitive_ranking_pattern"),
        "edge_length_extreme_bias": inspect_overactive_label(cards, "edge_length_extreme_bias"),
    }


def build_markdown(report):
    lines = []
    lines.append("# TSP S4a Validation Aggregate")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at_utc']}`")
    lines.append(f"- Run count: `{len(report['run_dirs'])}`")
    lines.append("")
    lines.append("## Diagnosis Frequency")
    lines.append("")
    for scope, counts in report["diagnosis_frequency"].items():
        lines.append(f"### {scope.replace('_', ' ').title()}")
        if not counts:
            lines.append("- none")
        else:
            for label, count in counts.items():
                lines.append(f"- `{label}`: `{count}`")
        lines.append("")
    lines.append("## Generation Metrics")
    lines.append("")
    for row in report["generation_metrics"]:
        lines.append(
            "- "
            + f"`{row['run_id']}` gen `{row['generation']}`: "
            + f"behavior_duplicate_ratio=`{row['behavior_duplicate_ratio']}`, "
            + f"objective_duplicate_ratio=`{row['objective_duplicate_ratio']}`, "
            + f"unique_behavior_signature_count=`{row['unique_behavior_signature_count']}`, "
            + f"mean_nearest_neighbor_pick_rate=`{row['mean_nearest_neighbor_pick_rate']}`, "
            + f"mean_chosen_rank_ratio=`{row['mean_chosen_rank_ratio']}`, "
            + f"mean_rank_bucket_entropy=`{row['mean_rank_bucket_entropy']}`"
        )
    lines.append("")
    lines.append("## Threshold Stability")
    lines.append("")
    for key, payload in report["threshold_stability"].items():
        lines.append(f"### {key}")
        lines.append(f"- assessment: `{payload.get('assessment')}`")
        for field, value in payload.items():
            if field == "assessment":
                continue
            lines.append(f"- `{field}`: `{value}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Aggregate TSP S4a validation runs.")
    parser.add_argument("--run-dir", action="append", dest="run_dirs", help="Run directory to include. Can be passed multiple times.")
    parser.add_argument("--latest", type=int, default=0, help="Use the latest N run directories under ./runs when --run-dir is not provided.")
    parser.add_argument("--output-json", help="Optional output JSON path.")
    parser.add_argument("--output-md", help="Optional output markdown path.")
    args = parser.parse_args()

    if args.run_dirs:
        run_dirs = [os.path.abspath(path) for path in args.run_dirs]
    else:
        runs_root = os.path.join(REPO_ROOT, "runs")
        latest = args.latest or 3
        run_dirs = latest_run_dirs(runs_root, latest)

    all_cards = []
    all_summaries = []
    for run_dir in run_dirs:
        cards, summaries = discover_behavior_artifacts(run_dir)
        all_cards.extend([card for card in cards if is_tsp_card(card)])
        all_summaries.extend([summary for summary in summaries if is_tsp_summary(summary)])

    report = {
        "generated_at_utc": utc_now_iso(),
        "run_dirs": run_dirs,
        "diagnosis_frequency": summarize_label_frequencies(all_cards),
        "generation_metrics": build_generation_rows(all_summaries),
        "threshold_stability": build_threshold_stability(all_cards),
    }

    output_json = os.path.abspath(args.output_json) if args.output_json else os.path.join(REPO_ROOT, "analysis", "tsp_s4a_validation_report.json")
    output_md = os.path.abspath(args.output_md) if args.output_md else os.path.join(REPO_ROOT, "analysis", "tsp_s4a_validation_report.md")

    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    os.makedirs(os.path.dirname(output_md), exist_ok=True)

    with open(output_json, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
    with open(output_md, "w", encoding="utf-8") as file:
        file.write(build_markdown(report))

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nJSON report written to: {output_json}")
    print(f"Markdown report written to: {output_md}")


if __name__ == "__main__":
    main()
