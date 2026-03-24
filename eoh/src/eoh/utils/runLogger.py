import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_json_default(value):
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, set):
        return sorted(value)
    return repr(value)


def _append_jsonl(path, record):
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, default=_safe_json_default))
        file.write("\n")


def _write_json(path, record):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(record, file, indent=2, ensure_ascii=False, default=_safe_json_default)


def _write_text(path, content):
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


def _sha256_text(content):
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_filename_part(value, max_len=64):
    if value is None:
        return "none"
    value = str(value)
    cleaned = []
    for ch in value:
        if ch.isalnum() or ch in ["-", "_", "."]:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    safe = "".join(cleaned).strip("._")
    if not safe:
        safe = "value"
    return safe[:max_len]


def _git_info(cwd):
    info = {"commit": None, "remote_origin": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode == 0:
            info["commit"] = commit.stdout.strip()
    except Exception:
        pass

    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if remote.returncode == 0:
            info["remote_origin"] = remote.stdout.strip()
    except Exception:
        pass

    return info


def _sanitize_paras(paras):
    sanitized = {}
    for key, value in vars(paras).items():
        if key == "exp_logger":
            continue
        if key == "llm_api_key":
            sanitized[key] = "<redacted>" if value else value
            continue
        sanitized[key] = value
    return sanitized


class RunLogger:
    def __init__(self, base_output_path):
        self.base_output_path = os.path.abspath(base_output_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = f"{timestamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.run_dir = os.path.join(self.base_output_path, "runs", self.run_id)
        self.logs_dir = os.path.join(self.run_dir, "logs")
        self.prompts_dir = os.path.join(self.logs_dir, "prompts")
        self.responses_dir = os.path.join(self.logs_dir, "responses")
        self.posthoc_dir = os.path.join(self.run_dir, "posthoc_eval")
        self.behavior_dir = os.path.join(self.run_dir, "behavior")
        self.behavior_cards_dir = os.path.join(self.behavior_dir, "cards")
        self.behavior_raw_traces_dir = os.path.join(self.behavior_dir, "raw_traces")
        self.behavior_generation_summaries_dir = os.path.join(self.behavior_dir, "generation_summaries")
        self.behavior_cards_index_path = os.path.join(self.behavior_dir, "heuristic_cards_index.jsonl")

        self.run_manifest_path = os.path.join(self.run_dir, "run_manifest.json")
        self.candidate_attempts_path = os.path.join(self.logs_dir, "candidate_attempts.jsonl")
        self.invalid_candidates_path = os.path.join(self.logs_dir, "invalid_candidates.jsonl")
        self.run_summary_path = os.path.join(self.run_dir, "run_summary.json")
        self._behavior_card_index_ids = set()

        self.start_time = time.time()
        self.stats = {
            "candidate_attempts": 0,
            "valid_candidates": 0,
            "invalid_candidates": 0,
            "llm_requests": 0,
            "llm_retry_responses": 0,
        }

        for path in [
            self.run_dir,
            self.logs_dir,
            self.prompts_dir,
            self.responses_dir,
            self.posthoc_dir,
            self.behavior_dir,
            self.behavior_cards_dir,
            self.behavior_raw_traces_dir,
            self.behavior_generation_summaries_dir,
        ]:
            os.makedirs(path, exist_ok=True)

    def build_manifest(self, paras, extra=None):
        extra = extra or {}
        manifest = {
            "run_id": self.run_id,
            "started_at_utc": _utc_now_iso(),
            "base_output_path": self.base_output_path,
            "run_dir": self.run_dir,
            "cwd": os.getcwd(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "argv": sys.argv,
            "git": _git_info(os.getcwd()),
            "paths": {
                "run_manifest": self.run_manifest_path,
                "candidate_attempts": self.candidate_attempts_path,
                "invalid_candidates": self.invalid_candidates_path,
                "run_summary": self.run_summary_path,
                "posthoc_dir": self.posthoc_dir,
                "behavior_dir": self.behavior_dir,
                "behavior_cards": self.behavior_cards_dir,
                "behavior_raw_traces": self.behavior_raw_traces_dir,
                "behavior_generation_summaries": self.behavior_generation_summaries_dir,
                "behavior_cards_index": self.behavior_cards_index_path,
            },
            "paras": _sanitize_paras(paras),
        }
        manifest.update(extra)
        return manifest

    def write_manifest(self, manifest):
        _write_json(self.run_manifest_path, manifest)

    def _persist_llm_trace(self, attempt_id, llm_trace):
        if not llm_trace:
            return None

        trace = dict(llm_trace)
        prompt = trace.get("prompt")
        responses = list(trace.get("responses") or [])
        request_id = trace.get("request_id") or uuid.uuid4().hex
        safe_attempt_id = _safe_filename_part(attempt_id)
        safe_request_id = _safe_filename_part(request_id)
        os.makedirs(self.prompts_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

        prompt_filename = f"{safe_attempt_id}__{safe_request_id}__prompt.txt"
        prompt_path = os.path.join(self.prompts_dir, prompt_filename)
        try:
            if prompt is not None:
                _write_text(prompt_path, prompt)
        except OSError as exc:
            return {
                "request_id": request_id,
                "prompt_file": None,
                "prompt_sha256": _sha256_text(prompt),
                "response_files": [],
                "response_sha256": [_sha256_text(response) for response in responses],
                "response_count": len(responses),
                "parse_success": trace.get("parse_success"),
                "parse_error": trace.get("parse_error"),
                "parse_retry_count": max(len(responses) - 1, 0),
                "trace_persist_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "stage": "prompt_write",
                },
            }

        response_paths = []
        for index, response in enumerate(responses, start=1):
            response_filename = f"{safe_attempt_id}__{safe_request_id}__response_{index}.txt"
            response_path = os.path.join(self.responses_dir, response_filename)
            try:
                _write_text(response_path, response)
                response_paths.append(response_path)
            except OSError as exc:
                return {
                    "request_id": request_id,
                    "prompt_file": prompt_path if prompt is not None else None,
                    "prompt_sha256": _sha256_text(prompt),
                    "response_files": response_paths,
                    "response_sha256": [_sha256_text(response) for response in responses],
                    "response_count": len(responses),
                    "parse_success": trace.get("parse_success"),
                    "parse_error": trace.get("parse_error"),
                    "parse_retry_count": max(len(responses) - 1, 0),
                    "trace_persist_error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "stage": "response_write",
                    },
                }

        self.stats["llm_requests"] += 1
        if len(responses) > 1:
            self.stats["llm_retry_responses"] += len(responses) - 1

        return {
            "request_id": request_id,
            "prompt_file": prompt_path if prompt is not None else None,
            "prompt_sha256": _sha256_text(prompt),
            "response_files": response_paths,
            "response_sha256": [_sha256_text(response) for response in responses],
            "response_count": len(responses),
            "parse_success": trace.get("parse_success"),
            "parse_error": trace.get("parse_error"),
            "parse_retry_count": max(len(responses) - 1, 0),
        }

    def log_candidate_attempt(self, record):
        record = dict(record)
        attempt_id = record.get("attempt_id") or uuid.uuid4().hex
        record["attempt_id"] = attempt_id
        record["logged_at_utc"] = _utc_now_iso()

        llm_trace = record.pop("llm_trace", None)
        record["llm_trace_files"] = self._persist_llm_trace(attempt_id, llm_trace)

        _append_jsonl(self.candidate_attempts_path, record)
        self.stats["candidate_attempts"] += 1

        if record.get("status") == "valid":
            self.stats["valid_candidates"] += 1
        else:
            self.stats["invalid_candidates"] += 1
            _append_jsonl(self.invalid_candidates_path, record)
        return record

    def write_heuristic_card(self, card):
        candidate_id = card["identity"]["candidate_id"]
        path = os.path.join(self.behavior_cards_dir, f"candidate_{candidate_id}.json")
        _write_json(path, card)
        if candidate_id not in self._behavior_card_index_ids:
            _append_jsonl(
                self.behavior_cards_index_path,
                {
                    "candidate_id": candidate_id,
                    "generation": card["identity"]["generation"],
                    "operator": card["identity"]["operator"],
                    "valid": card["identity"]["valid"],
                    "objective": card["identity"]["objective"],
                    "primary_label": card["diagnosis"].get("primary_label"),
                    "card_path": path,
                },
            )
            self._behavior_card_index_ids.add(candidate_id)
        return path

    def write_behavior_trace(self, candidate_id, payload):
        path = os.path.join(self.behavior_raw_traces_dir, f"candidate_{candidate_id}.json")
        _write_json(path, payload)
        return path

    def write_generation_behavior_summary(self, generation, summary):
        path = os.path.join(self.behavior_generation_summaries_dir, f"generation_{int(generation):03d}.json")
        _write_json(path, summary)
        return path

    def write_summary(self, summary):
        summary = dict(summary)
        summary["run_id"] = self.run_id
        summary["ended_at_utc"] = _utc_now_iso()
        summary["elapsed_seconds"] = round(time.time() - self.start_time, 6)
        summary["logger_stats"] = dict(self.stats)
        _write_json(self.run_summary_path, summary)
