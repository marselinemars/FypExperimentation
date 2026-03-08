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


def select_sample_cards(cards, limit=5):
    ordered = sorted(
        cards,
        key=lambda card: (
            card["_run_id"],
            card["identity"]["generation"],
            card["identity"]["candidate_id"],
        ),
    )
    selected = []
    used_generation_keys = set()
    for card in ordered:
        generation_key = (card["_run_id"], card["identity"]["generation"])
        if generation_key in used_generation_keys:
            continue
        selected.append(card)
        used_generation_keys.add(generation_key)
        if len(selected) >= limit:
            return selected

    for card in ordered:
        if card in selected:
            continue
        selected.append(card)
        if len(selected) >= limit:
            break
    return selected


def select_generation_summaries(summaries, limit=3):
    ordered = sorted(
        summaries,
        key=lambda summary: (summary["_run_id"], summary.get("generation", -1)),
    )
    return ordered[:limit]


def summarize_label_frequencies(cards):
    total_labels = Counter()
    primary_labels = Counter()
    label_confidences = defaultdict(list)

    for card in cards:
        diagnosis = card.get("diagnosis") or {}
        primary = diagnosis.get("primary_label")
        if primary:
            primary_labels[primary] += 1
        for label in diagnosis.get("labels") or []:
            total_labels[label] += 1
            if diagnosis.get("confidence") is not None:
                label_confidences[label].append(diagnosis["confidence"])

    return {
        "total_label_counts": dict(sorted(total_labels.items())),
        "primary_label_counts": dict(sorted(primary_labels.items())),
        "average_confidence_by_label": {
            label: round(sum(values) / len(values), 4)
            for label, values in sorted(label_confidences.items())
            if values
        },
    }


def build_generation_metric_table(summaries):
    rows = []
    for summary in sorted(summaries, key=lambda item: (item["_run_id"], item.get("generation", -1))):
        rows.append(
            {
                "run_id": summary["_run_id"],
                "generation": summary.get("generation"),
                "behavior_duplicate_ratio": summary.get("behavior_duplicate_ratio"),
                "collapse_risk_ratio": summary.get("collapse_risk_ratio"),
                "unique_behavior_signature_count": summary.get("number_of_unique_behavioral_signatures"),
                "candidate_count": summary.get("candidate_count"),
                "valid_candidate_count": summary.get("valid_candidate_count"),
            }
        )
    return rows


def threshold_review(cards):
    valid_cards = [card for card in cards if card["identity"]["valid"]]
    valid_count = len(valid_cards) or 1
    label_counts = Counter()
    label_confidences = defaultdict(list)

    for card in valid_cards:
        diagnosis = card.get("diagnosis") or {}
        for label in diagnosis.get("labels") or []:
            label_counts[label] += 1
            if diagnosis.get("confidence") is not None:
                label_confidences[label].append(diagnosis["confidence"])

    stable = []
    noisy = []
    for label, count in sorted(label_counts.items()):
        frequency = count / valid_count
        avg_conf = sum(label_confidences[label]) / len(label_confidences[label]) if label_confidences[label] else 0.0
        if count >= 2 and avg_conf >= 0.75 and frequency <= 0.85:
            stable.append(
                {
                    "label": label,
                    "count": count,
                    "frequency": round(frequency, 4),
                    "average_confidence": round(avg_conf, 4),
                }
            )
        if frequency > 0.85 or (count == 1 and avg_conf < 0.75):
            noisy.append(
                {
                    "label": label,
                    "count": count,
                    "frequency": round(frequency, 4),
                    "average_confidence": round(avg_conf, 4),
                }
            )

    return {
        "stable_and_meaningful": stable,
        "too_aggressive_or_noisy": noisy,
        "note": "This is a provisional rule-based review based on observed label frequency and confidence, not a final calibration.",
    }


def slim_card(card):
    return {
        "run_id": card["_run_id"],
        "generation": card["identity"]["generation"],
        "candidate_id": card["identity"]["candidate_id"],
        "operator": card["identity"]["operator"],
        "objective": card["identity"]["objective"],
        "valid": card["identity"]["valid"],
        "primary_label": card["diagnosis"].get("primary_label"),
        "labels": card["diagnosis"].get("labels"),
        "choice_trace_signature": card["behavior"].get("choice_trace_signature"),
        "behavior_duplicate_group_id": card["duplicates"].get("behavior_duplicate_group_id"),
        "objective_duplicate_group_id": card["duplicates"].get("objective_duplicate_group_id"),
        "card_path": card["_card_path"],
    }


def slim_summary(summary):
    return {
        "run_id": summary["_run_id"],
        "generation": summary.get("generation"),
        "candidate_count": summary.get("candidate_count"),
        "valid_candidate_count": summary.get("valid_candidate_count"),
        "behavior_duplicate_ratio": summary.get("behavior_duplicate_ratio"),
        "collapse_risk_ratio": summary.get("collapse_risk_ratio"),
        "unique_behavior_signature_count": summary.get("number_of_unique_behavioral_signatures"),
        "diagnosis_label_counts": summary.get("diagnosis_label_counts"),
        "summary_path": summary["_summary_path"],
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize completed S4a validation runs.")
    parser.add_argument("--run-dir", action="append", dest="run_dirs", help="Run directory to include. Can be passed multiple times.")
    parser.add_argument("--latest", type=int, default=0, help="Use the latest N run directories under ./runs when --run-dir is not provided.")
    parser.add_argument("--output", help="Optional output JSON path.")
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
        all_cards.extend(cards)
        all_summaries.extend(summaries)

    report = {
        "generated_at_utc": utc_now_iso(),
        "run_dirs": run_dirs,
        "sample_heuristic_cards": [slim_card(card) for card in select_sample_cards(all_cards, limit=5)],
        "sample_generation_summaries": [slim_summary(summary) for summary in select_generation_summaries(all_summaries, limit=3)],
        "diagnosis_label_frequency_table": summarize_label_frequencies(all_cards),
        "generation_behavior_metrics": build_generation_metric_table(all_summaries),
        "threshold_review_note": threshold_review(all_cards),
    }

    output_path = os.path.abspath(args.output) if args.output else os.path.join(REPO_ROOT, "analysis", "s4a_validation_report.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nReport written to: {output_path}")


if __name__ == "__main__":
    main()

