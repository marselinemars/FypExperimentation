# Phase 1 TSP Validation Pass

This note defines the next TSP-focused Phase 1 / S4a validation batch.

## Goal

Run 2-3 additional `tsp_construct` S4a validations and aggregate:

- diagnosis frequency
- duplicate ratios
- unique behavior signatures
- threshold stability

The specific label checks for this batch are:

- whether `behaviorally_duplicate` remains selective
- whether `unstable_start_sensitive` continues to separate candidates meaningfully
- whether `repetitive_ranking_pattern` remains overactive
- whether `edge_length_extreme_bias` remains overactive

## Recommended Runs

1. Smoke check if needed:

```bash
python scripts/run_baseline.py --config configs/smoke_tsp_construct.yaml
```

2. Then run the validation config 2-3 times:

```bash
python scripts/run_baseline.py --config configs/s4a_validation_tsp_construct.yaml
```

This keeps the run small enough for Phase 1 diagnosis while still generating real TSP HeuristicCards and generation summaries.

## Aggregation

After the runs complete, aggregate them with:

```bash
python scripts/summarize_tsp_s4a_validation.py --latest 3
```

Or pass specific run directories:

```bash
python scripts/summarize_tsp_s4a_validation.py \
  --run-dir runs/<run_id_1> \
  --run-dir runs/<run_id_2> \
  --run-dir runs/<run_id_3>
```

Outputs:

- `analysis/tsp_s4a_validation_report.json`
- `analysis/tsp_s4a_validation_report.md`

## What The Aggregate Report Contains

- diagnosis frequency over all TSP cards
- generation-by-generation duplicate ratios
- generation-by-generation unique behavior signature counts
- generation-level means for:
  - nearest-neighbor pick rate
  - chosen-rank ratio
  - rank-bucket entropy
- threshold stability review for:
  - `behaviorally_duplicate`
  - `unstable_start_sensitive`
  - `repetitive_ranking_pattern`
  - `edge_length_extreme_bias`

## Interpretation Guidance

The aggregation should be treated as a threshold-validation step, not a method-comparison result.

Strong signs that the TSP S4a layer is behaving well:

- `behaviorally_duplicate` remains selective rather than firing on most valid cards
- `unstable_start_sensitive` tracks higher alternate-start sensitivity than unlabeled cards
- `repetitive_ranking_pattern` and `edge_length_extreme_bias` do not saturate nearly all valid cards
- multiple generations retain more than one unique behavioral signature

If these conditions hold across the next 2-3 runs, then TSP remains a good Phase 1 architecture-prototyping domain before later transfer back to `bp_online`.
