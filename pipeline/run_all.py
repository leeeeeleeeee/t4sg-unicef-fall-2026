import argparse
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE = REPO_ROOT / "pipeline"
ANSWER_KEY = REPO_ROOT / "data" / "answer_key.csv"


def step(title, script, *args):
    print(f"\n=== {title} ===", flush=True)
    done = subprocess.run([sys.executable, str(PIPELINE / script), *map(str, args)], cwd=REPO_ROOT)
    if done.returncode != 0:
        sys.exit(f"Stopped: {script} failed (exit {done.returncode}). Fix it, then rerun"
                 + (" with --skip-ask to keep the answers already collected." if script != "runner.py" else "."))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_file")
    parser.add_argument("--refresh-key", action="store_true", help="rebuild data/answer_key.csv from the APIs")
    parser.add_argument("--skip-ask", action="store_true", help="don't call the models; reuse results.csv")
    parser.add_argument("--check-links", action="store_true", help="also test cited links in the report")
    args = parser.parse_args()

    run_file = Path(args.run_file).resolve()
    with open(run_file) as f:
        run_name = yaml.safe_load(f)["run_name"]
    results = REPO_ROOT / "results" / run_name / "results.csv"

    if args.refresh_key or not ANSWER_KEY.exists():
        step("1/4 Answer key", "answer_key.py")
    else:
        print(f"=== 1/4 Answer key: using existing {ANSWER_KEY.relative_to(REPO_ROOT)} (--refresh-key to rebuild) ===")

    if args.skip_ask:
        if not results.exists():
            sys.exit(f"--skip-ask: {results.relative_to(REPO_ROOT)} doesn't exist yet")
        print("=== 2/4 Ask models: skipped (--skip-ask) ===")
    else:
        step("2/4 Ask models", "runner.py", run_file)

    step("3/4 Score", "scorer.py", results, "--inplace")
    step("4/4 Report", "report.py", results, *(["--check-links"] if args.check_links else []))
    print(f"\nAll done. Charts and summary: results/{run_name}/report/summary.md")


if __name__ == "__main__":
    main()
