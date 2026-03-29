import argparse
import os
import subprocess
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(description="Run the TSP S4a diagnostic reasoner against the latest runs or an existing aggregate report.")
    parser.add_argument("--latest", type=int, default=3, help="Use the latest N runs when --report-json and --run-dir are not provided.")
    parser.add_argument("--run-dir", action="append", dest="run_dirs", help="Run directory to include. Can be passed multiple times.")
    parser.add_argument("--report-json", help="Use an existing aggregate report JSON instead of rebuilding it.")
    parser.add_argument("--dry-run", action="store_true", help="Only build the aggregate report and prompt without calling the LLM.")
    args = parser.parse_args()

    command = [sys.executable, os.path.join(REPO_ROOT, "scripts", "reason_about_tsp_s4a_validation.py")]
    if args.report_json:
        command.extend(["--report-json", args.report_json])
    else:
        if args.run_dirs:
            for run_dir in args.run_dirs:
                command.extend(["--run-dir", run_dir])
        else:
            command.extend(["--latest", str(args.latest)])
    if args.dry_run:
        command.append("--dry-run")

    raise SystemExit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
