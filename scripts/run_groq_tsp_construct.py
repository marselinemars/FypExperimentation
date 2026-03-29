import argparse
import os
import subprocess
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CONFIG = os.path.join(REPO_ROOT, "configs", "groq_s4a_validation_tsp_construct.yaml")


def main():
    parser = argparse.ArgumentParser(description="Run the TSP S4a Groq validation config with environment-driven overrides.")
    parser.add_argument("--validate-only", action="store_true", help="Validate config resolution without launching search.")
    parser.add_argument("--skip-posthoc", action="store_true", help="Skip post-hoc evaluation after search.")
    args = parser.parse_args()

    command = [sys.executable, os.path.join(REPO_ROOT, "scripts", "run_baseline.py"), "--config", DEFAULT_CONFIG]
    if args.validate_only:
        command.append("--validate-only")
    if args.skip_posthoc:
        command.append("--skip-posthoc")

    raise SystemExit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
