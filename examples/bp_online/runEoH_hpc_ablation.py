import os

from eoh import eoh
from eoh.utils.getParas import Paras


paras = Paras()

llm_api_endpoint = os.environ.get("EOH_LLM_API_ENDPOINT", "http://vllm-nodeport.vllm-ns.svc.cluster.local:8000/v1")
llm_api_key = os.environ.get("EOH_LLM_API_KEY", "")
llm_model = os.environ.get("EOH_LLM_MODEL", "Qwen3.5-122B-A10B-FP8")
eva_timeout = int(os.environ.get("EOH_EVA_TIMEOUT", "240"))

if not llm_api_key:
    raise RuntimeError("EOH_LLM_API_KEY is empty. Set it in the environment before running this ablation.")

paras.set_paras(
    method="eoh",
    problem="bp_online",
    llm_api_endpoint=llm_api_endpoint,
    llm_api_key=llm_api_key,
    llm_model=llm_model,
    ec_pop_size=4,
    ec_n_pop=4,
    exp_n_proc=4,
    exp_debug_mode=False,
)
paras.eva_timeout = eva_timeout

evolution = eoh.EVOL(paras)
evolution.run()
