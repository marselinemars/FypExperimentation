# Reasoning / Acting Probe Note

This branch adds an experimental prompt mode for probing how well the current LLM handles short explicit reasoning and action planning before producing code.

## What Changes

- The search and evaluation loop stays the same.
- The main change is prompt format.
- When `llm.reasoning_mode: react_v1` is enabled, prompts ask the model to respond in this shape:
  - `Reasoning:`
  - `Action:`
  - `{one-sentence algorithm description}`
  - final code in a fenced Python block

The raw responses are already archived through the existing LLM trace logging, so this mode is intended for direct inspection of reasoning quality in the saved response files.

## Dedicated Config

- [groq_reasoning_tsp_construct.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/groq_reasoning_tsp_construct.yaml)

## Dedicated Runner

- [run_groq_reasoning_tsp_construct.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/run_groq_reasoning_tsp_construct.py)

## Example

```bash
export GROQ_API_KEY='...'
export EOH_API_ENDPOINT='https://api.groq.com/openai/v1'
export EOH_MODEL='llama-3.3-70b-versatile'
export EOH_N_PROC=1
export EOH_POP_SIZE=2
export EOH_N_POP=2
export EOH_API_TIMEOUT=250
export EOH_EVAL_TIMEOUT=250

python scripts/run_groq_reasoning_tsp_construct.py
```
