# Week 01 Patch Log

## Scope

This file records baseline-fork changes applied on top of upstream commit:

- `492782aefe03bade9eba621d0a43f5652c7c7202`

The purpose of this log is to prevent silent drift.

## Change Classification

- Allowed in S0 now: instrumentation, protocol support, output organization
- Not yet included in S0: adaptive control, prompt optimization, memory, behavior-aware conditioning, selection/survival changes

## Current Fork Delta

### 0. Manifest sanitization

- File: [runLogger.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/runLogger.py)
- Behavior added:
  - redacts `llm_api_key` in `run_manifest.json`
  - excludes the live `exp_logger` object from manifest serialization
- Why baseline-safe:
  - affects logging only
  - prevents secret leakage and noisy object serialization

### 1. Run logger utility

- File: [runLogger.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/runLogger.py)
- Added: new `RunLogger` class
- Behavior added:
  - creates a unique run ID
  - creates a unique run directory
  - writes `run_manifest.json`
  - writes `logs/candidate_attempts.jsonl`
  - writes `logs/invalid_candidates.jsonl`
  - writes prompt and response text files
  - writes `run_summary.json`
  - collects basic logger stats
- Why baseline-safe:
  - no operator, prompt, evaluation, selection, or survival logic is changed
  - this is artifact management and structured logging only
- Validation done:
  - Python compile check passed
  - import smoke test passed

### 2. Unique run directory and run manifest

- File: [eoh.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/eoh.py)
- Function: `EVOL.__init__`
- Behavior added:
  - creates a `RunLogger`
  - rewrites `paras.exp_output_path` to a unique run directory
  - exposes `exp_run_id`, `exp_run_dir`, `exp_logger`, `exp_base_output_path`
- Why baseline-safe:
  - changes output destination only
  - no search decision reads the new metadata

- File: [eoh.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/eoh.py)
- Function: `EVOL.run`
- Behavior added:
  - writes `run_manifest.json`
  - writes `run_summary.json` at the end
- Why baseline-safe:
  - pure metadata write

### 3. EOH run summary exposure

- File: [eoh.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/methods/eoh/eoh.py)
- Functions: `EOH.__init__`, `EOH.run`, `EOH.get_run_summary`
- Behavior added:
  - stores logger handle
  - stores saved population file paths
  - stores final best candidate summary
  - passes generation/operator context into `InterfaceEC.get_algorithm`
- Why baseline-safe:
  - operator loop, weights, selection, survival, and evaluation calls remain unchanged
  - added context is used for logging only

### 4. Prompt/response trace capture

- File: [eoh_evolution.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/methods/eoh/eoh_evolution.py)
- Functions: `_get_alg`, `i1`, `e1`, `e2`, `m1`, `m2`, `m3`
- Behavior added:
  - capture prompt text
  - capture all raw LLM responses including parse retries
  - return trace metadata upward
- Why baseline-safe:
  - prompt text is unchanged relative to upstream
  - response parsing regex and retry structure are unchanged
  - the original failure mode is preserved: if parsing never succeeds, downstream execution still fails as before
- Validation done:
  - compared against upstream `HEAD:eoh/src/eoh/methods/eoh/eoh_evolution.py`
  - prompt strings matched
  - compile check passed

### 5. Candidate attempt logging

- File: [eoh_interface_EC.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/methods/eoh/eoh_interface_EC.py)
- Functions: `__init__`, `_get_alg`, `get_offspring`, `get_algorithm`
- Behavior added:
  - attempt ID creation
  - parent fingerprint logging
  - code and algorithm hashing
  - elapsed-time capture
  - valid/invalid status logging
  - prompt/response trace handoff to `RunLogger`
  - invalid candidate archive write
- Why baseline-safe:
  - candidate generation and evaluation calls are unchanged in order
  - invalid candidates still produce `objective = None` and are filtered out later
  - parent process performs file writes after worker results return
- Approximate lineage only:
  - exact stable candidate IDs do not exist upstream
  - current logging stores parent objective and parent code/algorithm hashes

### 6. Post-hoc evaluation mirroring

- File: [runEval.py](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/bp_online/evaluation/runEval.py)
- File: [runEval.py](C:/Users/pc%20omen/Documents/experimentation/EoH/examples/tsp_construct/evaluation/runEval.py)
- Behavior added:
  - if `EOH_RUN_DIR` is present, mirror evaluation `results.txt` into the same run folder
- Why baseline-safe:
  - original local `results.txt` output remains
  - evaluation math is unchanged

### 7. Unified S0 runner

- File: [run_baseline.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/run_baseline.py)
- Behavior added:
  - loads the versioned baseline YAML config
  - constructs `Paras` from config rather than from a scattered example script
  - copies the config snapshot into the run directory
  - runs EOH search
  - aggregates operator usage from `candidate_attempts.jsonl`
  - materializes the final best heuristic into a post-hoc evaluation workspace
  - runs the post-hoc evaluation script and records stdout and stderr under the run folder
- Why baseline-safe:
  - uses the existing `EVOL` and problem evaluators unchanged
  - does not alter prompts, operators, selection, survival, or evaluator semantics
  - post-hoc evaluation happens after search and only reads the final best code

### 8. Operator-weight bug fix

- File: [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- Function: `Paras.set_ec`
- Bug fixed:
  - changed `self.ec_operator` to `self.ec_operators` in operator-weight length validation
- Why this belongs in S0:
  - this restores the intended handling of external operator-weight configuration
  - without this fix, a config-driven baseline runner crashes before launch
- Behavioral note:
  - this does not change upstream defaults when weights are omitted
  - it only restores the intended config path when weights are supplied

### 9. Explicit S0 seed plumbing

- File: [seeding.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/seeding.py)
- File: [getParas.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/utils/getParas.py)
- File: [eoh.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/eoh.py)
- File: [eoh.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/methods/eoh/eoh.py)
- File: [eoh_interface_EC.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/methods/eoh/eoh_interface_EC.py)
- File: [run_baseline.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/run_baseline.py)
- File: [baseline_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/baseline_bp_online.yaml)
- Behavior added:
  - explicit `exp_seed`, `exp_python_seed`, `exp_numpy_seed`, and `exp_worker_seed`
  - deterministic main-process Python and NumPy seeding
  - deterministic worker-attempt seed derivation from operator, population, initialization batch, and task index
  - deterministic evaluation reseeding inside each worker attempt
  - config-level freezing of the seed regime for S0
- Why this belongs in S0:
  - upstream randomness was only partially controlled
  - this patch makes the local search loop and worker execution schedule reproducible enough to serve as a frozen thesis baseline fork
- Behavioral note:
  - this does change the exact stochastic envelope relative to raw upstream behavior
  - this is intentional and must be treated as part of the S0 baseline definition, not as "original upstream EOH"

### 10. Frozen HPC endpoint and model

- File: [baseline_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/baseline_bp_online.yaml)
- File: [week01_frozen_baseline.md](C:/Users/pc%20omen/Documents/experimentation/EoH/docs/week01_frozen_baseline.md)
- File: [week01_protocol_s0.md](C:/Users/pc%20omen/Documents/experimentation/EoH/docs/week01_protocol_s0.md)
- Behavior added:
  - froze the S0 endpoint to `http://vllm-nodeport.vllm-ns.svc.cluster.local:8000/v1`
  - froze the S0 model to `Qwen3.5-122B-A10B-FP8`
  - documented that real runs must be launched from the HPC Jupyter environment
  - kept the API key out of versioned config and documented env-based injection
- Why baseline-safe:
  - this freezes execution context without changing search logic
  - it prevents secret leakage into config snapshots and version control

### 11. Notebook convenience launcher

- File: [s0_bp_online_runner.ipynb](C:/Users/pc%20omen/Documents/experimentation/EoH/notebooks/s0_bp_online_runner.ipynb)
- Behavior added:
  - wraps `scripts/run_baseline.py` from a Jupyter notebook
  - validates config
  - launches the baseline run
  - inspects the latest run directory with a simple artifact checklist
- Why baseline-safe:
  - the notebook does not implement a separate experiment path
  - it delegates to the same S0 runner and config used from the command line

### 12. Strict post-run verifier

- File: [verify_run.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/verify_run.py)
- Behavior added:
  - verifies required run artifacts exist
  - validates `run_manifest.json` and `run_summary.json` required fields
  - validates `candidate_attempts.jsonl` required fields
  - checks prompt and response files referenced by JSONL records
  - checks invalid-candidate archive consistency
  - checks logger stats and operator-usage summary consistency
  - optionally requires successful post-hoc evaluation artifacts
- Why baseline-safe:
  - verification only
  - no search, evaluation, or generation behavior is modified

### 13. HTTP and full-base-URL support for remote LLM endpoint

- File: [api_general.py](C:/Users/pc%20omen/Documents/experimentation/EoH/eoh/src/eoh/llm/api_general.py)
- Behavior added:
  - supports full endpoint URLs with scheme and optional base path
  - supports both `http` and `https`
  - preserves backward compatibility for the upstream bare-host HTTPS mode
- Why this belongs in S0:
  - the frozen HPC deployment uses `http://.../v1`
  - upstream `InterfaceAPI` always used `HTTPSConnection` and always appended `/v1/chat/completions`, which made the HPC endpoint unusable from the baseline fork
- Behavioral note:
  - this is transport-layer compatibility only
  - prompt, operator, selection, survival, and evaluator logic are unchanged

### 14. Separate smoke-test configuration

- File: [smoke_bp_online.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/smoke_bp_online.yaml)
- File: [s0_bp_online_runner.ipynb](C:/Users/pc%20omen/Documents/experimentation/EoH/notebooks/s0_bp_online_runner.ipynb)
- Behavior added:
  - introduced a separate low-budget smoke config
  - set the notebook to use the smoke config by default
  - preserved the frozen baseline config unchanged
- Smoke-specific settings:
  - `population_size = 2`
  - `n_populations = 1`
  - `parallel_workers = 1`
  - `timeout_seconds = 180`
- Why baseline-safe:
  - this isolates pipeline diagnosis from the frozen S0 baseline
  - no baseline result needs to be reinterpreted or contaminated by smoke-test settings

## Risks Still Open

- The S0 runner is not yet unified. The upstream example script is still the active launcher.
- The versioned config file is not yet wired into execution.
- Seed behavior is not yet fully frozen across Python, NumPy, workers, and model sampling.
- Exact lineage IDs are still unavailable without a deeper structural patch.
- Operator usage is not yet summarized separately in `run_summary.json`.

## Validation Completed So Far

- `python -m py_compile` passed for all modified files
- import smoke test passed for `RunLogger` and `Paras`
- direct upstream comparison completed for `eoh_evolution.py`

## Next Patch Candidates For S0

- explicit baseline config wiring
- unified baseline runner
- explicit seed logging and optional seed propagation
- operator usage summary
- automatic search plus post-hoc evaluation wrapper
