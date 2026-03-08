# Phase 1 Validation Pass

This note is for the Phase 1 / S4a validation batch only. It does not add any new search behavior. It only validates that the behavior-aware layer is writing usable artifacts and that the v1 diagnosis rules are informative on real runs.

## Run Batch

1. Smoke run:

```bash
python scripts/run_baseline.py --config configs/smoke_bp_online.yaml
```

2. Real S4a runs:

Run the baseline config 2-3 times:

```bash
python scripts/run_baseline.py --config configs/baseline_bp_online.yaml
```

All three configs currently enable the S4a layer through:

- `behavior.enabled: true`
- `behavior.system_id: S4a`
- `behavior.config_path: configs/behavior_bp_online_v1.yaml`

## Expected Behavior Artifacts

Each run should contain:

- `behavior/cards/`
- `behavior/raw_traces/`
- `behavior/generation_summaries/`
- `behavior/heuristic_cards_index.jsonl`

## Validation Report

After the smoke run and the 2-3 real runs complete, generate the Phase 1 validation report:

```bash
python scripts/summarize_s4a_validation.py --latest 4 --output analysis/s4a_validation_report.json
```

Or pass specific run directories:

```bash
python scripts/summarize_s4a_validation.py `
  --run-dir runs/<run_id_smoke> `
  --run-dir runs/<run_id_real_1> `
  --run-dir runs/<run_id_real_2> `
  --run-dir runs/<run_id_real_3> `
  --output analysis/s4a_validation_report.json
```

## What The Report Returns

- 5 sample HeuristicCards from different candidates/generations when available
- 2-3 generation summaries
- diagnosis label frequency table
- behavioral duplicate ratio by generation
- collapse-risk ratio by generation
- unique behavior signature count by generation
- short threshold review note

## Threshold Interpretation

The thresholds in `configs/behavior_bp_online_v1.yaml` are provisional v1 defaults. The validation pass is intended to judge:

- which labels are stable and meaningful on real runs
- which labels appear too aggressive or too noisy

Threshold changes should only be made after reviewing the real validation report, not before.
