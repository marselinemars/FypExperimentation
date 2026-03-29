# Groq Runner Note

This note documents the dedicated Groq-backed runner/config path added for EOH experiments without replacing the existing HPC configs.

## Provider Path

- Base URL: `https://api.groq.com/openai/v1`
- Request path: `POST /chat/completions`
- Auth: `Authorization: Bearer <GROQ_API_KEY>`

The remote client now accepts a full OpenAI-compatible `base_url` and appends `/chat/completions` to the configured base path.

## Dedicated Config

- [groq_s4a_validation_tsp_construct.yaml](C:/Users/pc%20omen/Documents/experimentation/EoH/configs/groq_s4a_validation_tsp_construct.yaml)

This leaves the existing HPC validation configs unchanged.

## Dedicated Runner

- [run_groq_tsp_construct.py](C:/Users/pc%20omen/Documents/experimentation/EoH/scripts/run_groq_tsp_construct.py)

Example:

```bash
export GROQ_API_KEY='...'
export EOH_API_ENDPOINT='https://api.groq.com/openai/v1'
export EOH_MODEL='llama-3.3-70b-versatile'
export EOH_N_PROC=1
export EOH_POP_SIZE=2
export EOH_N_POP=2
export EOH_API_TIMEOUT=250
export EOH_EVAL_TIMEOUT=250

python scripts/run_groq_tsp_construct.py
```

## Supported Env Vars

The runner/client now supports:

- `GROQ_API_KEY` or `API_KEY`
- `EOH_API_ENDPOINT`
- `EOH_MODEL`
- `EOH_API_TIMEOUT`
- `EOH_EVAL_TIMEOUT`
- `EOH_N_PROC`
- `EOH_POP_SIZE`
- `EOH_N_POP`

Backward-compatible `EOH_LLM_*` env vars remain supported.
