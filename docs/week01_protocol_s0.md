# Week 01 Protocol Note for S0

## Protocol Status

Draft protocol for the thesis baseline fork.

This note is intended to freeze the baseline procedure for Week 01.
Any field still marked unresolved must be finalized before the first real experimental run.

## System Definition

- Baseline system name: `S0 - Thesis baseline fork of EOH`
- Upstream origin: `https://github.com/FeiLiu36/EoH.git`
- Frozen starting commit: `492782aefe03bade9eba621d0a43f5652c7c7202`
- Local runner: [run_baseline.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/run_baseline.py)
- Reference config: [baseline_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/baseline_bp_online.yaml)
- Patch ledger: [week01_patch_log.md](C:/Users/pc%20omen/Documents/experimentation/EoH/docs/week01_patch_log.md)

## Execution Environment

- Required environment for real runs: JupyterLab on the school HPC platform
- Reason: the frozen LLM endpoint is internal to that platform and is not expected to be reachable from a normal local machine session
- Frozen endpoint: `http://vllm-nodeport.vllm-ns.svc.cluster.local:8000/v1`
- Frozen model: `Qwen3.5-122B-A10B-FP8`
- API key handling policy:
  - do not store the key in versioned config
  - set `EOH_LLM_API_KEY` in the HPC session before running

## Problem Domain

- Main thesis problem in Week 01: `bp_online`
- Search-time prompt file: [prompts.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/prompts.py)
- Search-time evaluator: [run.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/run.py)
- Search-time dataset source: [get_instance.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/get_instance.py)
- Post-hoc evaluation script: [runEval.py](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/bp_online/evaluation/runEval.py)

## Search-Time Evaluation Definition

The generated candidate must define:

- `score(item, bins)`

Search-time evaluation behavior:

1. Generated code is executed with `exec` inside [run.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/run.py).
2. The heuristic is evaluated on the embedded `Weibull 5k` search dataset from [get_instance.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/problems/optimization/bp_online/get_instance.py).
3. The optimized scalar objective is:
   - `fitness = (avg_num_bins - lb) / lb`
4. Lower is better.

## Post-Hoc Test Definition

Post-hoc evaluation uses:

- [runEval.py](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/bp_online/evaluation/runEval.py)
- test data in [testingdata](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/bp_online/evaluation/testingdata)

The current test script evaluates across:

- capacities: `100`, `300`, `500`
- sizes: `1k`, `5k`, `10k`

The S0 runner copies the final best heuristic into an isolated evaluation workspace under the run directory and then executes the post-hoc test script there.

## Fixed Search Configuration for S0

These are the currently frozen search settings from the S0 config:

- `method = "eoh"`
- `problem = "bp_online"`
- `selection = "prob_rank"`
- `management = "pop_greedy"`
- `population_size = 4`
- `n_populations = 4`
- `n_parents_e1_e2 = 2`
- `operators = ["e1", "e2", "m1", "m2"]`
- `operator_weights = [1, 1, 1, 1]`
- `parallel_workers = 4`
- `debug_mode = false`
- `timeout_seconds = 20`
- `use_numba_decorator = true`

## Fixed Operator Set and Order

Operator order in S0:

1. `e1`
2. `e2`
3. `m1`
4. `m2`

Each operator weight is currently `1`, and the EOH loop applies the operator whenever `np.random.rand() < op_w`.
Under the current weights, every operator is attempted in every saved population.

## Budget Definition

For the current EOH configuration:

- initialization uses `2 * population_size = 8` `i1` attempts
- each saved population uses `len(operators) * population_size = 16` attempts
- with `n_populations = 4`, the total planned candidate attempts are:
  - `8 + 4 * 16 = 72`

This is the nominal candidate-attempt budget before duplicate retries and failures.

## Invalid Candidate Definition

A candidate is considered invalid if any of the following occurs:

- the LLM response cannot be parsed into algorithm text and code
- the generated code fails during `exec`
- the generated code fails during evaluator execution
- the evaluator returns `None`
- the attempt exceeds timeout or raises another exception on the evaluation path

Invalid candidates are archived in `logs/invalid_candidates.jsonl`.

## Logging and Artifacts

S0 currently produces:

- `run_manifest.json`
- `run_summary.json`
- `logs/candidate_attempts.jsonl`
- `logs/invalid_candidates.jsonl`
- prompt files
- response files
- saved population JSON files
- saved best-per-generation JSON files
- post-hoc evaluation stdout and stderr
- copied post-hoc evaluation outputs under the same run directory
- copied config snapshot under the same run directory

## Artifact Folder Structure

Current intended run structure:

- `runs/<run_id>/run_manifest.json`
- `runs/<run_id>/run_summary.json`
- `runs/<run_id>/config_snapshot.yaml`
- `runs/<run_id>/logs/candidate_attempts.jsonl`
- `runs/<run_id>/logs/invalid_candidates.jsonl`
- `runs/<run_id>/logs/prompts/`
- `runs/<run_id>/logs/responses/`
- `runs/<run_id>/results/pops/`
- `runs/<run_id>/results/pops_best/`
- `runs/<run_id>/posthoc_eval/bp_online/`

## Seed and Reproducibility Policy

Frozen S0 seed regime:

- `global_seed = 2024`
- `python_seed = 2024`
- `numpy_seed = 2024`
- `worker_seed_base = 2024`
- worker seed strategy:
  - deterministic per attempt from operator, population index, initialization batch, and task index

Implications:

- parent selection randomness is now explicitly seeded in worker attempts
- NumPy operator gating in the main loop is now explicitly seeded
- evaluation-time Python and NumPy randomness inside worker attempts is explicitly reseeded

Still not frozen by this patch:

- backend-side LLM sampling nondeterminism unless the selected backend exposes and receives a seed or deterministic generation setting

## HPC Launch Procedure

From the HPC Jupyter terminal or notebook shell, the intended S0 command is:

```bash
export EOH_LLM_API_KEY="my-key-ensia-2022-1030"
python scripts/run_baseline.py
```

Windows PowerShell equivalent:

```powershell
$env:EOH_LLM_API_KEY = "my-key-ensia-2022-1030"
python scripts/run_baseline.py
```

The endpoint and model are already frozen in the config file. The key should be injected only at run time.

## Baseline-Fork Fixes Included in S0

Currently included in S0:

- instrumentation and run logging
- unique run directories
- config-driven launcher
- config snapshot saving
- post-hoc evaluation attachment
- operator-weight bug fix in [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)

## Systems Planned After S0

- `S0` = thesis baseline fork of EOH
- `S2` = calibrated or adaptive control
- `S4` = behavior-aware planner
- `S5` = minimal episodic memory

These later systems must be compared against this same frozen S0 fork rather than against a moving upstream reference.

## Open Items Before First Real S0 Run

- finalize backend and model
- finalize sampling-parameter policy
- finalize seed regime for S0
- run smoke test through the S0 runner
- verify full artifact completeness in one real run folder
