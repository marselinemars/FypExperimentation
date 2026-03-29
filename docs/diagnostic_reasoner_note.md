# Diagnostic Reasoner Note

This branch adds a post-run diagnostic reasoner for the TSP S4a workflow.

The goal is not to change search behavior. The search loop, prompts, survivor management, and evaluator stay unchanged.

Instead, the new script:

1. reads aggregated TSP S4a diagnostics
2. asks an OpenAI-compatible LLM to interpret those diagnostics
3. returns a structured analysis with:
   - summary
   - observations
   - likely failure mode
   - confidence
   - evidence used
   - recommended next actions
   - threshold review
   - questions to answer next

## Scripts

- `scripts/reason_about_tsp_s4a_validation.py`
  - builds or reads the aggregate TSP report
  - calls the LLM
  - writes JSON + markdown outputs
- `scripts/run_groq_diagnostic_reasoner.py`
  - convenience wrapper for the Groq/OpenAI-compatible setup

## Environment

The script uses:

- `GROQ_API_KEY` or `API_KEY`
- `EOH_API_ENDPOINT`
- `EOH_MODEL`
- `EOH_API_TIMEOUT`

Example:

```bash
export GROQ_API_KEY='...'
export EOH_API_ENDPOINT='https://api.groq.com/openai/v1'
export EOH_MODEL='llama-3.3-70b-versatile'
export EOH_API_TIMEOUT=250
```

## Typical usage

After producing 2-3 TSP S4a runs:

```bash
python scripts/run_groq_diagnostic_reasoner.py --latest 3
```

This writes:

- `analysis/tsp_s4a_validation_report.json`
- `analysis/tsp_s4a_reasoner_prompt.txt`
- `analysis/tsp_s4a_reasoner_raw_response.txt`
- `analysis/tsp_s4a_reasoner_report.json`
- `analysis/tsp_s4a_reasoner_report.md`

## Why this exists

This is an experiment-advisor layer, not a heuristic-generation layer.

It is meant to help answer questions like:

- which diagnosis labels look stable?
- which thresholds look too aggressive?
- what is the most evidence-backed next intervention?
- what should be tested next before changing the search policy?
