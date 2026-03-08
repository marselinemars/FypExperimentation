# Week 01 Frozen Baseline Definition

## Status

Draft S0 definition for the thesis baseline fork.

This file defines the baseline system as a controlled fork, not as "untouched upstream EOH".
All later systems must build on top of this same frozen fork once the open decisions below are finalized.

## Baseline Name

`S0 - Thesis baseline fork of EOH`

## Code Origin

- Upstream repository: `https://github.com/FeiLiu36/EoH.git`
- Frozen starting commit: `492782aefe03bade9eba621d0a43f5652c7c7202`
- Local fork root: [EoH](C:/Users/pc%20omen/Documents/experimentation/EoH)

## Main Thesis Problem

- Primary problem for Week 01: `bp_online`
- Search evaluator: [run.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/run.py)
- Search dataset source: [get_instance.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/get_instance.py)
- Prompt definitions: [prompts.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/prompts.py)
- Post-hoc test script: [runEval.py](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/bp_online/evaluation/runEval.py)

## Current Baseline Launcher

- Current upstream-style launcher: [runEoH.py](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/bp_online/runEoH.py)
- S0 unified runner: [run_baseline.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/run_baseline.py)

The S0 runner reads the versioned config file and is intended to replace the example script for thesis runs.

## Current Fixed Search Settings From Upstream Example

- `method = "eoh"`
- `problem = "bp_online"`
- `ec_pop_size = 4`
- `ec_n_pop = 4`
- `exp_n_proc = 4`
- `selection = "prob_rank"` via defaults in [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- `management = "pop_greedy"` via defaults in [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- `ec_m = 2` via defaults in [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- `ec_operators = ["e1", "e2", "m1", "m2"]` via defaults in [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- `ec_operator_weights = [1, 1, 1, 1]` via defaults in [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- `eva_timeout = 20` for `bp_online` via [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- `eva_numba_decorator = True` for `bp_online` via [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)

## Frozen S0 Execution Environment

- Intended execution environment: JupyterLab running on the school HPC platform
- Reason: the chosen LLM endpoint is only reachable from that HPC environment
- Frozen S0 endpoint: `http://vllm-nodeport.vllm-ns.svc.cluster.local:8000/v1`
- Frozen S0 model: `Qwen3.5-122B-A10B-FP8`

Model-history note:

- You reported that `QuantTrio/Qwen3-VL-235B-A22B-Instruct-AWQ` was previously used and later became unavailable.
- You also reported that a previous fallback resolution found `Qwen3.5-122B-A10B-FP8` with timestamp `2026-03-22 22:30:13 UTC`.
- That timestamp is later than the current session date `2026-03-08`, so I am treating it as a user-supplied external run note, not as something verified from this environment.
- For S0, the frozen model string is therefore the user-supplied fallback model `Qwen3.5-122B-A10B-FP8`.

## Current Thesis-Fork Instrumentation Already Added

These changes are already present in the local fork and must be documented as part of S0:

- unique run directory per run
- `run_manifest.json`
- `logs/candidate_attempts.jsonl`
- `logs/invalid_candidates.jsonl`
- prompt archive
- response archive
- `run_summary.json`
- optional mirroring of post-hoc evaluation output into the run folder

See [week01_patch_log.md](C:/Users/pc%20omen/Documents/experimentation/EoH/docs/week01_patch_log.md) for the exact file-level patch record.

## Open Decisions That Must Be Frozen Before First Real S0 Run

- explicit model sampling parameters if the backend exposes them
- whether the backend can be made deterministic beyond the current seed plumbing

The seed regime is now frozen as part of S0:

- Python seed: `2024`
- NumPy seed: `2024`
- worker seed base: `2024`
- worker seed strategy: deterministic per attempt from run context

These settings are now part of the thesis baseline fork and must stay fixed across later systems unless a separate ablation explicitly changes them.

## Baseline Statement For Thesis Use

Recommended wording:

> We use a thesis baseline fork of EOH, derived from commit `492782aefe03bade9eba621d0a43f5652c7c7202`, with documented protocol, logging, and output-management modifications. All later paradigms are implemented on top of this same frozen fork rather than compared against a drifting upstream copy.

## Immediate Next Actions

1. Finalize any exposed backend sampling parameters.
2. Use the smoke config to verify end-to-end pipeline health.
3. Use the prebaseline config to test a controlled scale-up before full S0.
4. Run the frozen baseline config only after smoke and prebaseline pass.

## Scale-Up Ladder

To avoid contaminating S0 while still diagnosing pipeline limits, the current intended progression is:

1. Smoke diagnostic:
   - [smoke_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/smoke_bp_online.yaml)
   - purpose: prove end-to-end pipeline viability under reduced load
2. Prebaseline scale-up:
   - [prebaseline_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/prebaseline_bp_online.yaml)
   - purpose: test near-baseline search shape with reduced concurrency pressure
3. Frozen S0 baseline:
   - [baseline_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/baseline_bp_online.yaml)
   - purpose: produce baseline results for thesis comparison
