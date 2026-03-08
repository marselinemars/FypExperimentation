import os

import yaml


DEFAULT_CONFIG = {
    "enabled": True,
    "system_id": "S4a",
    "objective_duplicate_epsilon": 1e-9,
    "trace": {
        "traced_instance_ids": ["test_0", "test_1"],
        "trace_prefix_steps": 200,
        "permutation_seed": 2024,
        "tie_score_epsilon": 1e-12,
        "near_full_leftover_ratio": 0.1,
        "near_empty_leftover_ratio": 0.8,
    },
    "thresholds": {
        "high_symmetry_duplicate_capacity_rate": 0.95,
        "high_symmetry_tie_hit_rate": 0.20,
        "high_symmetry_chosen_group_size": 50.0,
        "low_confidence_margin_mean": 0.001,
        "aggressive_opening_ratio_first_third": 0.20,
        "fragmentation_var_leftover": 150.0,
        "fragmentation_mean_leftover_low": 15.0,
        "fragmentation_mean_leftover_high": 50.0,
        "robustness_score_drop": 0.002,
        "narrow_generalization_score_drop": 0.005,
        "low_instance_variance_bins_used": 50.0,
        "high_instance_variance_bins_used": 200.0,
    },
    "notes": {
        "thresholds_version": "v1_provisional_defaults",
        "threshold_policy": "Thresholds are initial rule-based defaults and should be calibrated with empirical runs later.",
    },
}


def _deep_merge(base, updates):
    merged = dict(base)
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_behavior_config(config_path=None):
    config = dict(DEFAULT_CONFIG)
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        config = _deep_merge(config, loaded)
    return config

