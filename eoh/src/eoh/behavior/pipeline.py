import os
import re

from .bp_online_trace import BPOnlineTraceExtractor
from .config import load_behavior_config
from .heuristic_card import build_heuristic_card, finalize_generation
from .tsp_construct_trace import TSPConstructTraceExtractor


def _infer_problem_type(problem):
    class_name = problem.__class__.__name__
    if class_name == "BPONLINE":
        return "bp_online"
    if class_name == "TSPCONST":
        return "tsp_construct"
    return class_name.lower()


def _build_trace_extractor(problem, trace_config):
    class_name = problem.__class__.__name__
    if class_name == "BPONLINE":
        return BPOnlineTraceExtractor(problem, trace_config)
    if class_name == "TSPCONST":
        return TSPConstructTraceExtractor(problem, trace_config)
    raise ValueError(f"Unsupported behavior-aware problem class: {class_name}")


class BehaviorPipeline:
    def __init__(self, problem, logger, config_path=None, system_id="S4a"):
        self.problem = problem
        self.logger = logger
        self.config = load_behavior_config(config_path)
        self.system_id = system_id or self.config.get("system_id", "S4a")
        self.problem_type = _infer_problem_type(problem)
        self.objective_duplicate_epsilon = float(self.config.get("objective_duplicate_epsilon", 1e-9))
        self.thresholds = dict(self.config.get("thresholds") or {})
        self.trace_extractor = _build_trace_extractor(problem, self.config.get("trace") or {})
        self.cards_by_generation = {}
        self._finalized_generations = set()

    def analyze_and_log_candidate(self, record, offspring):
        generation = record.get("population_index", 0) or 0
        code_string = offspring.get("code") if offspring else None
        algorithm_text = offspring.get("algorithm") if offspring else None
        if not code_string or not algorithm_text:
            reconstructed = self._reconstruct_from_trace(record)
            if reconstructed is not None:
                code_string = code_string or reconstructed.get("code")
                algorithm_text = algorithm_text or reconstructed.get("algorithm")

        context = {
            "run_id": self.logger.run_id,
            "system_id": self.system_id,
            "problem_type": self.problem_type,
            "generation": generation,
            "candidate_id": record.get("attempt_id"),
            "operator": record.get("operator"),
            "parent_ids": [],
            "parent_code_hashes": [parent.get("code_sha256") for parent in record.get("parents") or [] if parent],
            "parent_objectives": [parent.get("objective") for parent in record.get("parents") or [] if parent],
            "code": code_string,
            "algorithm": algorithm_text,
            "objective": record.get("objective"),
            "valid": record.get("status") == "valid",
            "timeout": record.get("error_type") == "TimeoutError",
            "runtime_error": record.get("error_message"),
            "error_type": record.get("error_type"),
        }

        trace_result = None
        if context["valid"] and code_string:
            try:
                trace_result = self.trace_extractor.evaluate_candidate(code_string, bool(record.get("used_numba")))
            except Exception as exc:
                trace_result = {
                    "trace_error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                }

        card, raw_trace = build_heuristic_card(context, trace_result)
        self.cards_by_generation.setdefault(generation, []).append(card)
        self.logger.write_heuristic_card(card)
        self.logger.write_behavior_trace(card["identity"]["candidate_id"], raw_trace)
        return card

    def finalize_generation(self, generation):
        if generation in self._finalized_generations:
            return None
        cards = self.cards_by_generation.get(generation) or []
        if not cards:
            summary = {
                "generation": generation,
                "candidate_count": 0,
                "problem_type": self.problem_type,
                "valid_candidate_count": 0,
                "invalid_candidate_count": 0,
                "objective_duplicate_group_count": 0,
                "behavior_duplicate_group_count": 0,
                "number_of_objective_duplicates": 0,
                "number_of_behavioral_duplicates": 0,
                "number_of_unique_behavioral_signatures": 0,
                "number_of_collapse_risk_candidates": 0,
                "objective_duplicate_ratio": None,
                "behavior_duplicate_ratio": None,
                "collapse_risk_ratio": None,
                "diagnosis_label_counts": {},
                "objective_duplicate_epsilon": self.objective_duplicate_epsilon,
                "thresholds_status": "v1_provisional_defaults",
            }
        else:
            cards, summary = finalize_generation(cards, self.thresholds, self.objective_duplicate_epsilon)
            for card in cards:
                self.logger.write_heuristic_card(card)
        self.logger.write_generation_behavior_summary(generation, summary)
        self._finalized_generations.add(generation)
        return summary

    def _reconstruct_from_trace(self, record):
        trace = record.get("llm_trace_files") or {}
        response_files = trace.get("response_files") or []
        for response_file in response_files:
            if not os.path.exists(response_file):
                continue
            with open(response_file, "r", encoding="utf-8") as file:
                response_text = file.read()
            parsed = self._parse_response_to_code(response_text)
            if parsed is not None:
                return parsed
        return None

    def _parse_response_to_code(self, response_text):
        if not response_text:
            return None
        algorithm = re.findall(r"\{(.*)\}", response_text, re.DOTALL)
        if len(algorithm) == 0:
            if "python" in response_text:
                algorithm = re.findall(r"^.*?(?=python)", response_text, re.DOTALL)
            elif "import" in response_text:
                algorithm = re.findall(r"^.*?(?=import)", response_text, re.DOTALL)
            else:
                algorithm = re.findall(r"^.*?(?=def)", response_text, re.DOTALL)
        code = re.findall(r"import.*return", response_text, re.DOTALL)
        if len(code) == 0:
            code = re.findall(r"def.*return", response_text, re.DOTALL)
        if len(algorithm) == 0 and len(code) == 0:
            return None
        prompt_outputs = getattr(self.problem.prompts, "get_func_outputs", lambda: [])()
        suffix = ""
        if prompt_outputs:
            suffix = " " + ", ".join(prompt_outputs)
        return {
            "algorithm": algorithm[0] if algorithm else "unavailable",
            "code": (code[0] if code else None) + suffix if code else None,
        }
