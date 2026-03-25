import hashlib

from .diagnosis import assign_diagnosis
from .metrics import (
    compute_behavior_metrics,
    compute_robustness_metrics,
    compute_structure_metrics,
    null_behavior_metrics,
    null_robustness_metrics,
)


def sha256_text(value):
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _behavior_signature_key(card):
    performance = card.get("performance") or {}
    outcomes = performance.get("per_instance_outcomes") or {}
    if not outcomes:
        outcomes = performance.get("per_instance_bins_used") or {}
    return (
        card["behavior"].get("choice_trace_signature"),
        tuple(sorted(outcomes.items())),
    )


def build_heuristic_card(context, trace_result):
    code_string = context.get("code")
    algorithm_text = context.get("algorithm")
    valid = bool(context.get("valid"))

    performance = {
        "objective": context.get("objective"),
        "per_instance_scores": {},
        "per_instance_bins_used": {},
        "per_instance_outcomes": {},
        "valid_instance_count": 0,
        "timeout": bool(context.get("timeout", False)),
        "runtime_error": context.get("runtime_error"),
        "full_search_metrics": {
            "search_problem_metrics": [],
            "per_instance_scores": {},
            "per_instance_bins_used": {},
            "per_instance_outcomes": {},
            "valid_instance_count": 0,
        },
        "traced_instance_metrics": {
            "instance_ids": [],
            "per_instance_scores": {},
            "per_instance_bins_used": {},
            "per_instance_outcomes": {},
        },
    }

    behavior = null_behavior_metrics()
    robustness = null_robustness_metrics()
    raw_trace = {"trace_error": None, "traces": {}, "robustness": {}}
    if trace_result and valid and not trace_result.get("trace_error"):
        full_search = trace_result.get("full_search_metrics") or {}
        traced = trace_result.get("traced_instance_metrics") or {}
        performance["per_instance_scores"] = dict(full_search.get("per_instance_scores") or {})
        performance["per_instance_bins_used"] = dict(full_search.get("per_instance_bins_used") or {})
        performance["per_instance_outcomes"] = dict(full_search.get("per_instance_outcomes") or performance["per_instance_bins_used"])
        performance["valid_instance_count"] = full_search.get("valid_instance_count", 0)
        performance["full_search_metrics"] = full_search
        performance["traced_instance_metrics"] = traced
        behavior = compute_behavior_metrics(trace_result.get("traces"))
        robustness = compute_robustness_metrics(trace_result.get("robustness"))
        raw_trace = {
            "trace_error": None,
            "traces": trace_result.get("traces") or {},
            "robustness": trace_result.get("robustness") or {},
        }
    elif trace_result and trace_result.get("trace_error"):
        raw_trace["trace_error"] = trace_result["trace_error"]

    card = {
        "identity": {
            "run_id": context.get("run_id"),
            "system_id": context.get("system_id"),
            "generation": context.get("generation"),
            "candidate_id": context.get("candidate_id"),
            "operator": context.get("operator"),
            "parent_ids": context.get("parent_ids") or [],
            "code_hash": sha256_text(code_string),
            "objective": context.get("objective"),
            "valid": valid,
        },
        "structure": compute_structure_metrics(code_string, algorithm_text),
        "performance": performance,
        "behavior": behavior,
        "robustness": robustness,
        "diagnosis": {
            "labels": [],
            "primary_label": None,
            "confidence": None,
            "evidence": {},
            "error_type": context.get("error_type"),
        },
        "lineage": {
            "parent_code_hashes": context.get("parent_code_hashes") or [],
            "parent_objectives": context.get("parent_objectives") or [],
            "operator": context.get("operator"),
            "generation_created": context.get("generation"),
        },
        "duplicates": {
            "objective_duplicate_group_id": None,
            "behavior_duplicate_group_id": None,
            "is_objective_duplicate": False,
            "is_behavior_duplicate": False,
        },
    }
    return card, raw_trace


def finalize_generation(cards, thresholds, objective_duplicate_epsilon):
    valid_cards = [card for card in cards if card["identity"]["valid"] and card["identity"]["objective"] is not None]
    objective_groups = _group_objective_duplicates(valid_cards, objective_duplicate_epsilon)
    behavior_groups = _group_behavior_duplicates(valid_cards)

    objective_group_lookup = {}
    for index, group in enumerate(objective_groups, start=1):
        if len(group) <= 1:
            continue
        group_id = f"objdup_gen{cards[0]['identity']['generation']}_{index}"
        for card in group:
            objective_group_lookup[card["identity"]["candidate_id"]] = group_id

    behavior_group_lookup = {}
    for index, group in enumerate(behavior_groups, start=1):
        if len(group) <= 1:
            continue
        group_id = f"behdup_gen{cards[0]['identity']['generation']}_{index}"
        for card in group:
            behavior_group_lookup[card["identity"]["candidate_id"]] = group_id

    generation_objectives = [card["identity"]["objective"] for card in valid_cards]
    label_counts = {}
    collapse_risk_count = 0

    for card in cards:
        candidate_id = card["identity"]["candidate_id"]
        if candidate_id in objective_group_lookup:
            card["duplicates"]["objective_duplicate_group_id"] = objective_group_lookup[candidate_id]
            card["duplicates"]["is_objective_duplicate"] = True
        if candidate_id in behavior_group_lookup:
            card["duplicates"]["behavior_duplicate_group_id"] = behavior_group_lookup[candidate_id]
            card["duplicates"]["is_behavior_duplicate"] = True

        card["diagnosis"] = assign_diagnosis(
            card,
            thresholds,
            generation_context={"valid_objectives": generation_objectives},
        )
        for label in card["diagnosis"]["labels"]:
            label_counts[label] = label_counts.get(label, 0) + 1
        if "high_symmetry_collapse_risk" in card["diagnosis"]["labels"]:
            collapse_risk_count += 1

    valid_count = len(valid_cards)
    objective_duplicate_count = sum(1 for card in cards if card["duplicates"]["is_objective_duplicate"])
    behavior_duplicate_count = sum(1 for card in cards if card["duplicates"]["is_behavior_duplicate"])
    unique_behavior_signatures = {
        _behavior_signature_key(card)
        for card in valid_cards
        if card["behavior"].get("choice_trace_signature")
    }

    summary = {
        "generation": cards[0]["identity"]["generation"] if cards else None,
        "candidate_count": len(cards),
        "valid_candidate_count": valid_count,
        "invalid_candidate_count": len(cards) - valid_count,
        "objective_duplicate_group_count": sum(1 for group in objective_groups if len(group) > 1),
        "behavior_duplicate_group_count": sum(1 for group in behavior_groups if len(group) > 1),
        "number_of_objective_duplicates": objective_duplicate_count,
        "number_of_behavioral_duplicates": behavior_duplicate_count,
        "number_of_unique_behavioral_signatures": len(unique_behavior_signatures),
        "number_of_collapse_risk_candidates": collapse_risk_count,
        "objective_duplicate_ratio": (objective_duplicate_count / valid_count) if valid_count else None,
        "behavior_duplicate_ratio": (behavior_duplicate_count / valid_count) if valid_count else None,
        "collapse_risk_ratio": (collapse_risk_count / valid_count) if valid_count else None,
        "diagnosis_label_counts": label_counts,
        "objective_duplicate_epsilon": objective_duplicate_epsilon,
        "thresholds_status": "v1_provisional_defaults",
    }
    return cards, summary


def _group_objective_duplicates(cards, epsilon):
    if not cards:
        return []
    ordered = sorted(cards, key=lambda card: card["identity"]["objective"])
    groups = []
    current = [ordered[0]]
    anchor = ordered[0]["identity"]["objective"]
    for card in ordered[1:]:
        value = card["identity"]["objective"]
        if abs(value - anchor) <= epsilon:
            current.append(card)
        else:
            groups.append(current)
            current = [card]
            anchor = value
    groups.append(current)
    return groups


def _group_behavior_duplicates(cards):
    grouped = {}
    for card in cards:
        key = _behavior_signature_key(card)
        grouped.setdefault(key, []).append(card)
    return list(grouped.values())
