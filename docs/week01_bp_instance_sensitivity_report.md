# Week 01 BP Online Instance-Sensitivity Report

## Scope

This note documents the `bp_online` instance-sensitivity ablation performed after the S0 and S4a collapse diagnosis work.

The goal was to answer four questions:

1. Are the 5 embedded search instances behaviorally too similar?
2. Does one instance dominate the collapse?
3. Do alternative or perturbed instances produce more behavioral diversity?
4. Is the collapse mainly instance-set driven, evaluator/state driven, or both?

The analysis was run with:

- branch: `ablation/bp-instance-sensitivity`
- script: [analyze_bp_instance_sensitivity.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/analyze_bp_instance_sensitivity.py)
- run analyzed: `runs/20260324_212734_15467_f41b7393`

## Data Source

The final analysis used:

- candidate identity and validity from S4a behavior cards when available
- raw generated candidate code reconstructed directly from saved LLM response files
- replay on the embedded `Weibull 5k` search instances from the current `bp_online` search dataset

This was necessary because some runs did not expose all older candidate-attempt artifacts in the originally assumed locations.

## Result Summary

Eight valid candidates were reconstructed and replayed successfully.

Across the embedded 5 search instances:

- every instance produced exactly `1` unique choice-signature across all 8 candidates
- every instance produced exactly `1` unique bins-used value across all 8 candidates
- the per-instance duplicate ratio was `1.0` for all five instances
- the full 5-instance bins-used vector signature count was `1`
- the full 5-instance duplicate ratio was `1.0`

The shared per-instance bins-used vector for the 8 analyzed candidates was:

- `test_0 = 2094`
- `test_1 = 2059`
- `test_2 = 2057`
- `test_3 = 2067`
- `test_4 = 2058`

## Leave-One-Out Analysis

To test whether one embedded instance dominated the collapse, the analysis omitted each search instance in turn and recomputed the vector-signature diversity over the remaining 4-instance subset.

Result:

- omitting `test_0` still gave `1` unique subset signature
- omitting `test_1` still gave `1` unique subset signature
- omitting `test_2` still gave `1` unique subset signature
- omitting `test_3` still gave `1` unique subset signature
- omitting `test_4` still gave `1` unique subset signature

Conclusion:

- no single embedded instance dominated the collapse

## Perturbed-Instance Analysis

The script then evaluated the same 8 candidates on deterministic perturbations of the embedded instance set:

- `permute_seed_2024`
- `reverse_order`
- `sorted_desc`

These perturbations changed the absolute task outcomes. For example, under `permute_seed_2024`, the shared bins-used vector changed to:

- `test_0 = 2088`
- `test_1 = 2060`
- `test_2 = 2055`
- `test_3 = 2065`
- `test_4 = 2061`

However, they did **not** increase inter-candidate behavioral diversity:

- perturbed unique vector-signature count remained `1`
- perturbed duplicate ratio remained `1.0`
- per-instance unique choice-signature count remained `1`

Conclusion:

- perturbing the embedded instances changes the task realization
- but it does not separate the candidates from each other

## Interpretation

These results do **not** support the hypothesis that the collapse is mainly caused by one especially bad search instance, or by a poor embedded 5-instance set in isolation.

The evidence supports a stronger conclusion:

- under the current `bp_online` evaluator/state formulation, the analyzed candidate heuristics remain behaviorally indistinguishable even when the embedded search instances are perturbed

So the collapse is best characterized as:

- primarily **evaluator/state driven**

rather than:

- primarily **instance-set driven**

## Recommended Wording

The safest summary statement for supervisor-facing reporting is:

> Instance-sensitivity analysis did not identify a single dominant search instance, and deterministic perturbations of the embedded 5-instance set did not increase behavioral diversity among reconstructed valid candidates. Therefore, the observed `bp_online` collapse appears to be mainly evaluator/state driven rather than instance-set driven.

## Implication for Next Phases

This suggests that later post-baseline systems should focus first on mechanisms that can separate behavior under the current `bp_online` state representation, for example:

- richer behavioral state
- behavior-aware diversity preservation
- alternative tie handling
- behavior-aware lineage or survivor criteria

Changing the instance set alone is unlikely to resolve the collapse.
