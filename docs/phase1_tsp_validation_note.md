# Phase 1 TSP Validation Note

## Scope

This note records the first real Phase 1 / S4a validation results for `tsp_construct` on the thesis fork of EOH. This phase remains representation-only:

- no search-policy changes
- no prompt changes
- no survivor-management changes
- no memory or adaptive control

The goal of this run was to validate that the TSP-specific S4a architecture:

- executes end-to-end
- produces usable HeuristicCards
- produces generation summaries
- exposes behavior patterns more clearly than the earlier `bp_online` setting

## Run Outcome

The run completed successfully and did not exhibit the immediate full-collapse pattern previously observed in `bp_online`.

Console-level result:

- initial population best objective: `9.24425`
- valid generation-1 offspring objectives included:
  - `7.89656`
  - `6.60788`
  - `6.7415`
  - `6.69585`
  - `7.929`
- final population objectives:
  - `6.60788`
  - `6.69585`

This indicates meaningful objective separation and at least partial behavioral diversity, which makes `tsp_construct` a more suitable Phase 1 architecture-prototyping domain than `bp_online`.

## Generation Summaries

### Generation 0

From the first generation summary:

- `candidate_count = 4`
- `valid_candidate_count = 1`
- `invalid_candidate_count = 3`
- `objective_duplicate_ratio = 0.0`
- `behavior_duplicate_ratio = 0.0`
- `number_of_unique_behavioral_signatures = 1`
- `collapse_risk_ratio = 0.0`
- `mean_nearest_neighbor_pick_rate = 0.6041666666666666`
- `mean_chosen_rank_ratio = 0.06308503467447754`
- `mean_rank_bucket_entropy = 0.6170100901912516`

Interpretation:

- the TSP path was still validity-limited at initialization
- but it did not show the `bp_online`-style valid-candidate collapse

### Generation 1

From the next generation summary:

- `candidate_count = 8`
- `valid_candidate_count = 6`
- `invalid_candidate_count = 2`
- `objective_duplicate_ratio = 0.3333333333333333`
- `behavior_duplicate_ratio = 0.3333333333333333`
- `number_of_unique_behavioral_signatures = 5`
- `collapse_risk_ratio = 0.0`
- `mean_nearest_neighbor_pick_rate = 0.8940972222222222`
- `mean_chosen_rank_ratio = 0.011585776183421659`
- `mean_rank_bucket_entropy = 0.10632343113203531`

Interpretation:

- six valid candidates survived evaluation
- five unique behavioral signatures were observed
- behavior duplicates existed, but were partial rather than total
- the surviving policies were strongly local / nearest-neighbor biased

## Diagnosis Label Frequency

Across the two available generation summaries, the diagnosis label counts were:

- `invalid_candidate`: `5`
- `evaluation_invalid`: `3`
- `syntax_invalid`: `2`
- `overly_greedy_local_policy`: `6`
- `repetitive_ranking_pattern`: `7`
- `unstable_start_sensitive`: `5`
- `edge_length_extreme_bias`: `7`
- `behaviorally_duplicate`: `2`
- `narrow_generalization`: `3`

## Behavior Duplicate Ratio By Generation

- generation `0`: `0.0`
- generation `1`: `0.3333333333333333`

## Unique Behavior Signature Count By Generation

- generation `0`: `1`
- generation `1`: `5`

## Sample HeuristicCard Readout

Representative valid cards:

1. Best duplicate policy, objective `6.60788`
- rank-trace signature present
- `nearest_neighbor_pick_rate = 1.0`
- `mean_chosen_rank_ratio = 0.0`
- labeled:
  - `behaviorally_duplicate`
  - `overly_greedy_local_policy`
  - `repetitive_ranking_pattern`
  - `unstable_start_sensitive`
  - `narrow_generalization`
  - `edge_length_extreme_bias`

2. Distinct valid policy, objective `6.7415`
- not behaviorally duplicate
- `nearest_neighbor_pick_rate = 0.8229166666666666`
- `mean_chosen_rank_ratio = 0.035540482463564824`
- labeled:
  - `overly_greedy_local_policy`
  - `repetitive_ranking_pattern`
  - `edge_length_extreme_bias`

3. Less stable local policy, objective `7.89656`
- `alt_start_relative_score_delta = 0.048191769293911876`
- primary diagnosis:
  - `unstable_start_sensitive`

4. Another local policy with stronger start sensitivity, objective `7.929`
- `alt_start_relative_score_delta = 0.10811991132771681`
- primary diagnosis:
  - `unstable_start_sensitive`

Representative invalid cards:

1. Evaluation invalid:
- `NameError: name 'next_node' is not defined`

2. Syntax invalid:
- `SyntaxError: unterminated string literal`

These invalids confirm that the TSP evaluator error logging patch is working and that invalid-candidate cards remain analyzable.

## Main Interpretation

This validation run supports three conclusions.

First, the TSP S4a implementation is operational. The system produced valid candidate cards, invalid candidate cards, and generation summaries with TSP-specific behavior fields and generation-level aggregates.

Second, `tsp_construct` is currently a much cleaner Phase 1 prototyping domain than `bp_online`. Unlike `bp_online`, this run did not show immediate full behavioral collapse among valid candidates. Instead, the run showed:

- real objective differentiation
- partial rather than total behavior duplication
- multiple distinct rank-trace signatures in generation 1

Third, the dominant policy family in this run appears strongly local. Most valid candidates were diagnosed as nearest-neighbor-heavy or repetitive in ranking behavior, which is plausible for constructive TSP heuristics and gives the S4a layer meaningful structure to observe.

## Threshold Review

Labels that already look meaningful:

- `invalid_candidate`
- `syntax_invalid`
- `evaluation_invalid`
- `behaviorally_duplicate`
- `overly_greedy_local_policy`
- `unstable_start_sensitive`

Labels that currently look too aggressive or noisy and should remain provisional:

- `repetitive_ranking_pattern`
- `edge_length_extreme_bias`
- `narrow_generalization`

Reason:

- `repetitive_ranking_pattern` fired on most valid candidates
- `edge_length_extreme_bias` also fired on most valid candidates
- `narrow_generalization` may be over-triggering in this still-small validation sample

## Practical Follow-Up

This run is enough to justify continuing Phase 1 validation on TSP before returning to `bp_online` as the harder transfer domain. The next useful step is to collect 2-3 additional TSP S4a runs and aggregate:

- diagnosis frequency
- duplicate ratios
- unique behavior signature counts
- threshold stability

before any Phase 2 intervention work begins.
