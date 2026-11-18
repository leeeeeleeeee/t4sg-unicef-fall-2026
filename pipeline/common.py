"""Shared helpers for the evaluation scripts (scorer, judge, MCP test).

Keeps the shared column lists from the project brief in one place so every
script reads and writes files that fit together.
"""
from __future__ import annotations

import glob
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- Shared columns (from "Building our Benchmark Tool") -------------------
PROMPT_COLUMNS = [
    "id", "prompt", "user_type", "indicator", "country", "country_code",
    "indicator_code", "year", "common", "leading", "style", "wording", "detail",
]
ANSWER_KEY_COLUMNS = [
    "id", "unicef_value", "datacommons_value", "year", "range_low", "range_high",
    "unit", "source", "data_exists", "lag_flag",
]
RESULTS_COLUMNS = [
    "id", "model", "mode", "thinking", "web_search", "repeat", "answer",
    "headline_number", "year_given", "source_claimed", "searched", "caveat",
    "number_score", "year_score", "source_score", "error_types",
    "input_tokens", "output_tokens", "cost", "seconds",
]
# Extra columns the scorer appends AFTER the shared ones (safe for pandas readers).
SCORER_EXTRA_COLUMNS = [
    "official_value", "official_year", "number_value", "number_diff", "score_notes",
]

# ---- Week 1 error taxonomy (Kleef & Bianca, "Errors and Harms") -----------
TAXONOMY = [
    "Wrong number",
    "Outdated value",
    "Source misattribution",
    "Missing caveat",
    "Narrative distortion",
    "Did not fetch data",
    "Sycophantic agreement",
    "Pattern answer",
    "Entity / geography mix-up",
    "Indicator or unit mix-up",
    "Fabricated source",
    "Inconsistent answers",
]

NUMBER_SCORES = ["Correct", "Close", "Wrong", "Portal lag", "No number"]
YEAR_SCORES = ["Latest", "Outdated", "None"]
SOURCE_SCORES = ["Primary", "Secondary", "Misattributed", "None"]


def read_csv_str(path: str) -> pd.DataFrame:
    """Read a CSV keeping every cell as a string ('' for blanks)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def load_prompts(paths: list[str]) -> dict[str, dict]:
    """Load prompts from CSV files and/or folders of CSVs, keyed by id."""
    out: dict[str, dict] = {}
    for p in paths:
        files = sorted(glob.glob(os.path.join(p, "*.csv"))) if os.path.isdir(p) else [p]
        for f in files:
            df = read_csv_str(f)
            if "id" not in df.columns or "prompt" not in df.columns:
                continue  # not a prompt file (e.g. a template with other columns)
            for row in df.to_dict("records"):
                if not row["id"]:
                    continue
                if row["id"] in out and out[row["id"]].get("prompt") != row.get("prompt"):
                    print(f"warning: prompt id {row['id']} appears twice; using {os.path.basename(f)}",
                          file=sys.stderr)
                row["_prompt_file"] = os.path.basename(f)
                out[row["id"]] = row
    return out


def load_answer_key(path: str) -> dict[str, dict]:
    df = read_csv_str(path)
    return {r["id"]: r for r in df.to_dict("records") if r["id"]}


def to_float(x) -> float | None:
    try:
        if x is None or str(x).strip() == "":
            return None
        return float(str(x).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def is_percent_unit(unit: str) -> bool:
    u = (unit or "").lower()
    return "%" in u or "percent" in u or "percentage point" in u


def load_dotenv_if_present() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv(usecwd=True))
    except ImportError:
        pass


# ---- Names used by report.py and checks.py (Bianca) -------------------------
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(ROOT)
RESULT_COLUMNS = RESULTS_COLUMNS

_CANONICAL_SCORES = {s.lower(): s for s in NUMBER_SCORES + YEAR_SCORES + SOURCE_SCORES}


def clean_score(value) -> str:
    """Normalize a score cell ('correct ', 'NO NUMBER') to its canonical label; '' if blank."""
    v = str(value or "").strip()
    return _CANONICAL_SCORES.get(v.lower(), v)


def to_bool(value):
    """'Y'/'yes'/'true'/'1' -> True, 'N'/'no'/'false'/'0' -> False, anything else (e.g. 'Unclear') -> None."""
    v = str(value or "").strip().lower()
    if v in {"y", "yes", "true", "1", "on"}:
        return True
    if v in {"n", "no", "false", "0", "off"}:
        return False
    return None
