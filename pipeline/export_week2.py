"""Export our graded Week 2 spreadsheets into the shared columns (the scorer's test set).

Usage:
    python pipeline/export_week2.py --answer-key "Week 2_ Answer Key.xlsx" \
                                    --results "Week 2_ Benchmark Results.xlsx"

Writes to data/test_set/:
    week2_prompts.csv              prompts in the shared prompt columns
    week2_answer_key_original.csv  the answer key exactly as we recorded it by hand (normalized)
    week2_answer_key.csv           the answer key re-checked against UNICEF's SDMX API (use this one)
    answer_key_corrections.csv     every change between the two keys, with the reason and API query
    week2_results_hand.csv         our hand-graded answers in the shared results columns
    week2_hand_extras.csv          hand-only fields (tester, notes, follow-up source, ...) keyed by id+model

Notes on the export:
  * Excel stored many percentages as fractions with a % display format (0.332 shown as 33.2%).
    We read the cell format and write "33.2%" so the text matches what the grader saw.
  * Gemini's P4 headline "3-7" was auto-converted by Google Sheets into the date 7 March;
    it is restored to "3-7%".
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

import openpyxl
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ANSWER_KEY_COLUMNS, PROMPT_COLUMNS, RESULTS_COLUMNS, ROOT  # noqa: E402

OUT = os.path.join(ROOT, "data", "test_set")
SDMX = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,{flow},1.0/{key}?format=csv"
CHECKED_ON = "2026-11-16"

PER_1000 = "deaths per 1,000 live births"

# Per-prompt metadata the sheet doesn't hold cleanly: ISO3 code, the real indicator code
# (several rows had a description instead of a code), and the unit.
META = {
    "N1":   ("BGD", "CME_MRY0T4", PER_1000),
    "R1":   ("RWA", "CME_MRY0T4", PER_1000),
    "P1":   ("NGA", "CME_MRY0T4", PER_1000),
    "N4":   ("ETH", "PT_CHLD_Y0T4_REG", "%"),
    "R4":   ("IDN", "PT_CHLD_Y0T4_REG", "%"),
    "T1-1": ("MOZ", "NT_BW_LBW", "%"),
    "T1-2": ("ERI", "PT_F_0-14_FGM", "%"),
    "T1-3": ("BLZ", "ED_CR_L1", "%"),
    "T1-4": ("CMR", "WS_HCF_C-B", "%"),
    "T1-5": ("YEM", "IM_DTP1", "%"),
    "N2":   ("KEN", "IM_DTP3", "%"),
    "R2":   ("BRA", "IM_HEPBB", "%"),
    "P2":   ("TCD", "IM_DTP3", "%"),
    "P4":   ("ETH", "PT_CHLD_Y0T4_REG", "%"),
    "N5":   ("PAK", "NT_ANT_HAZ_NE2_MOD", "%"),
    "T2-1": ("CUB", "CME_MRY0T4", PER_1000),
    "T2-2": ("AFG", "ED_CR_L1", "%"),
    "T2-3": ("SRB", "PT_F_20-24_MRD_U18", "%"),
    "T2-4": ("SWZ", "ED_CR_L3", "percentage points"),
    "T2-5": ("LSO", "WS_PPL_W-SM", "%"),
    "N3":   ("KHM", "ED_CR_L3", "%"),
    "R3":   ("NPL", "ED_CR_L3", "%"),
    "P3":   ("NPL", "ED_CR_L3", "%"),
    "R5":   ("ETH", "NT_ANT_WAZ_NE2", "%"),
    "P5":   ("PAK", "NT_ANT_HAZ_NE2_MOD", "%"),
    "T3-1": ("MWI", "PT_F_20-24_MRD_U18", "%"),
    "T3-2": ("LAO", "NT_ANT_HAZ_NE2_MOD", "%"),
    "T3-3": ("COG", "WS_PPL_W-SM", "%"),
    "T3-4": ("BTN", "IM_MCV1", "%"),
    "T3-5": ("KEN", "CME_ARR_U5MR", "% per year"),
}

# Answer key re-checked against UNICEF's SDMX API on CHECKED_ON.
# Each entry: field -> (new value, reason, query key). Only fields that change are listed.
def _q(flow, key):
    return SDMX.format(flow=flow, key=key)

VERIFIED = {
    "N1": {"range_low": ("28.55", "Key had no range; UN IGME publishes one", _q("GLOBAL_DATAFLOW", "BGD.CME_MRY0T4._T")),
           "range_high": ("33.09", "", "")},
    "R1": {"year": ("2022", "Value 39.65 is the 2022 estimate (the prompt asks 2022); key said 2024 (2024 = 37.7)",
                    _q("GLOBAL_DATAFLOW", "RWA.CME_MRY0T4._T")),
           "range_low": ("31.22", "Key had no range", ""), "range_high": ("50.42", "", "")},
    "R4": {"data_exists": ("N", "UNICEF has no 2017 value for Indonesia (only SUSENAS 2025 = 86.8%). Prompt asks 2017",
                           _q("GLOBAL_DATAFLOW", "IDN.PT_CHLD_Y0T4_REG.")),},
    "T1-1": {"range_low": ("15.13", "Key had no range; modelled estimate has one", _q("GLOBAL_DATAFLOW", "MOZ.NT_BW_LBW.")),
             "range_high": ("20.71", "", "")},
    "T1-3": {"unicef_value": ("95.4", "API total (both sexes) is 95.4 (girls 96.0, boys 94.8); key had 95.1",
                              _q("GLOBAL_DATAFLOW", "BLZ.ED_CR_L1.")),},
    "N2": {"unicef_value": ("88", "Key row was blank. DTP3 is the standard 'fully vaccinated' proxy (Week 1 Data & Tools summary)",
                            _q("GLOBAL_DATAFLOW", "KEN.IM_DTP3.")),
           "year": ("2025", "", ""), "unit": ("%", "", ""),
           "source": ("WHO/UNICEF estimates of national immunization coverage (WUENIC), 2025 revision", "", ""),
           "data_exists": ("Y", "", "")},
    "R2": {"year": ("2018", "Brazil HepB birth dose in 2018 = 87% (HepB3 2018 is also 87%). Key said 2025, but 2025 = 82%",
                    _q("GLOBAL_DATAFLOW", "BRA.IM_HEPBB.")),},
    "P2": {"unicef_value": ("67", "Prompt asks 2023. Chad DTP3 2023 = 67%; the key's 71% is the 2025 value. "
                                  "All three chatbots said 67% and were hand-scored Wrong",
                            _q("GLOBAL_DATAFLOW", "TCD.IM_DTP3.")),
           "year": ("2023", "", "")},
    "T2-2": {"unicef_value": ("53.9", "Prompt asks primary completion: ED_CR_L1 = 53.9% (DHS 2015). Key used ED_CR_L3 "
                                      "(upper secondary) code with year 2025", _q("GLOBAL_DATAFLOW", "AFG.ED_CR_L1.")),
             "year": ("2015", "", ""), "source": ("DHS 2015", "", "")},
    "T2-4": {"unicef_value": ("2.16", "Female 33.31% minus male 31.15% (MICS 2014); key rounded to 2",
                              _q("GLOBAL_DATAFLOW", "SWZ.ED_CR_L3.")),},
    "R3": {"data_exists": ("N", "No 2021 value; nearest is MICS 2019 (27.6%)", _q("GLOBAL_DATAFLOW", "NPL.ED_CR_L3.F")),},
    "R5": {"unicef_value": ("21.22", "Prompt asks UNDERWEIGHT (weight-for-age, NT_ANT_WAZ_NE2 = 21.2%, 2019). Key used "
                                     "WASTING (6.8%). All three chatbots said ~21% and were hand-scored Wrong",
                            _q("GLOBAL_DATAFLOW", "ETH.NT_ANT_WAZ_NE2.")),
           "range_low": ("18.78", "", ""), "range_high": ("23.88", "", ""),
           "data_exists": ("N", "No 2022 survey value; latest is EMDHS 2019", "")},
    "P5": {"unicef_value": ("33.57", "Prompt asks UNICEF's LATEST figure: JME modelled 2024 = 33.6% (28.3-39.3). Key used the "
                                     "2018 DHS survey value (37.6%). Matches how N5 and T3-2 are keyed",
                            _q("GLOBAL_DATAFLOW", "PAK.NT_ANT_HAZ_NE2_MOD._T")),
           "year": ("2024", "", ""), "range_low": ("28.25", "", ""), "range_high": ("39.34", "", ""),
           "source": ("UNICEF/WHO/World Bank Joint Malnutrition Estimates (modelled)", "", "")},
}


def cell_text(cell) -> str:
    """Return a cell as the text a person saw in the sheet (fixing % and date mangling)."""
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        # Sheets turned "3-7" into 7 March. Restore "month-day" as a range.
        return f"{v.month}-{v.day}%"
    if isinstance(v, float):
        if "%" in (cell.number_format or ""):
            pct = round(v * 100, 4)
            return f"{pct:g}%"
        if v.is_integer():
            return str(int(v))
        return f"{v:g}"
    return str(v).strip()


def read_sheet(path: str) -> tuple[list[str], list[list]]:
    ws = openpyxl.load_workbook(path).worksheets[0]
    rows = list(ws.iter_rows())
    header = [str(c.value).strip() if c.value is not None else "" for c in rows[0]]
    body = [r for r in rows[1:] if any(c.value is not None for c in r)]
    return header, body


def norm_year(text: str) -> str:
    t = (text or "").strip()
    if re.fullmatch(r"\d{4}", t):
        return t
    if t.lower().startswith("latest"):
        return "latest"
    return ""  # "No year"


def parse_value(text: str, cell) -> tuple[str, str]:
    """Official value -> (number as text in display units, note)."""
    v = cell.value
    if isinstance(v, float):
        # Fractions without a % format in the key are still percentages (e.g. 0.1776 for 17.76%).
        if "%" in (cell.number_format or "") or v <= 1.0:
            return f"{round(v * 100, 4):g}", ""
        return f"{v:g}", ""
    m = re.search(r"(-?\d+(?:\.\d+)?)", str(v or ""))
    if not m:
        return "", "no number in key"
    note = "" if re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*%?\s*", str(v)) else f"key text: {v}"
    if "nearest is" in str(v):
        m = re.search(r"nearest is\s*(-?\d+(?:\.\d+)?)", str(v))
    return m.group(1), note


def parse_range(text: str) -> tuple[str, str]:
    t = (text or "").strip()
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(-?\d+(?:\.\d+)?)\s*$", t)
    return (m.group(1), m.group(2)) if m else ("", "")


def yn(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    if t.startswith("y"):
        return "Y"
    if t.startswith("n"):
        return "N"
    if t.startswith("unclear"):
        return "Unclear"
    return ""


def caveat_yn(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    if t.startswith("yes") or t.startswith("y,") or t == "y":
        return "Y"
    if t.startswith("no") or t.startswith("only after"):
        return "N"
    return "Y"  # free-text description of a caveat that was given (e.g. "Mentioned that ...")


def norm_score(text: str, allowed: list[str]) -> str:
    t = (text or "").strip()
    fixes = {"secoundary": "Secondary", "year not given": "None", "": ""}
    if t.lower() in fixes:
        return fixes[t.lower()]
    for a in allowed:
        if t.lower() == a.lower():
            return a
    return t


def export(answer_key_xlsx: str, results_xlsx: str) -> None:
    os.makedirs(OUT, exist_ok=True)

    # ---------------- Answer key + prompts ----------------
    header, body = read_sheet(answer_key_xlsx)
    col = {h: i for i, h in enumerate(header)}
    prompts, key_rows = [], []
    for r in body:
        rid = cell_text(r[col["ID"]])
        if not rid:
            continue
        code, ind_code, unit = META[rid]
        country = cell_text(r[col["Country"]]).replace("Lao PDF", "Lao PDR")
        prompts.append({
            "id": rid,
            "prompt": cell_text(r[col["Prompt (exact wording)"]]),
            "user_type": cell_text(r[col["User type"]]),
            "indicator": cell_text(r[col["Indicator"]]),
            "country": country,
            "country_code": code,
            "indicator_code": ind_code,
            # T2-2's sheet says 2022 but the prompt text has no year.
            "year": "" if rid == "T2-2" else norm_year(cell_text(r[col["Year in prompt"]])),
            "common": cell_text(r[col["Common or less common"]]).replace("More common", "Common"),
            "leading": cell_text(r[col["Leading or neutral"]]),
            "style": "", "wording": "", "detail": "",
        })
        value, _ = parse_value("", r[col["Official value"]])
        lo, hi = parse_range(cell_text(r[col["Uncertainty range (if given)"]]))
        if rid == "T3-5":
            lo, hi = "-0.1", "4.3"  # "-0.1-4.3" in the sheet
        key_year = cell_text(r[col["Year of official value"]])
        data_exists = "Y" if value else ""
        if "No value in" in str(r[col["Official value"]].value or ""):
            data_exists = "N"
        key_rows.append({
            "id": rid, "unicef_value": value, "datacommons_value": "",
            "year": key_year, "range_low": lo, "range_high": hi,
            "unit": unit if value else "",
            "source": cell_text(r[col["Original source (e.g. UN IGME, WHO/UNICEF, DHS)"]]),
            "data_exists": data_exists, "lag_flag": "",
        })

    pd.DataFrame(prompts, columns=PROMPT_COLUMNS).to_csv(os.path.join(OUT, "week2_prompts.csv"), index=False)
    original = pd.DataFrame(key_rows, columns=ANSWER_KEY_COLUMNS)
    original.to_csv(os.path.join(OUT, "week2_answer_key_original.csv"), index=False)

    verified = original.copy()
    changes = []
    for rid, fields in VERIFIED.items():
        idx = verified.index[verified["id"] == rid][0]
        reason_for_row = next((v[1] for v in fields.values() if v[1]), "")
        query = next((v[2] for v in fields.values() if v[2]), "")
        for field, (new, _reason, _q2) in fields.items():
            old = verified.at[idx, field]
            if str(old) != str(new):
                changes.append({"id": rid, "field": field, "original": old, "corrected": new,
                                "reason": reason_for_row, "api_query": query, "checked_on": CHECKED_ON})
            verified.at[idx, field] = new
    verified.to_csv(os.path.join(OUT, "week2_answer_key.csv"), index=False)
    pd.DataFrame(changes).to_csv(os.path.join(OUT, "answer_key_corrections.csv"), index=False)

    # ---------------- Hand-graded results ----------------
    header, body = read_sheet(results_xlsx)
    col = {h: i for i, h in enumerate(header)}

    def g(r, name):
        return cell_text(r[col[name]])

    results, extras = [], []
    for r in body:
        rid = g(r, "ID")
        model = f"{g(r, 'Chatbot')} {g(r, 'Model version')}".strip()
        year_given = g(r, "Year given")
        results.append({
            "id": rid, "model": model,
            "mode": "cold",  # consumer chat apps, no skill file, no MCP
            "thinking": yn(g(r, "Thinking mode on? (Y/N/Unclear)")),
            "web_search": yn(g(r, "Web search on? (Y/N/Unclear)")),
            "repeat": "1",
            "answer": "",  # full transcripts were not recorded in the sheet (screenshots only)
            "headline_number": g(r, "Headline number given"),
            "year_given": year_given,
            "source_claimed": g(r, "Source claimed (first answer)"),
            "searched": yn(g(r, "Searched during answer? (Y/N/Unclear)")),
            "caveat": caveat_yn(g(r, "Caveat included? (Y/N + what)")),
            "number_score": norm_score(g(r, "Number score (Correct/Close/Wrong/No number)"),
                                       ["Correct", "Close", "Wrong", "No number"]),
            "year_score": norm_score(g(r, "Year score (Latest/Outdated/None)"), ["Latest", "Outdated", "None"]),
            "source_score": norm_score(g(r, "Source score (Primary/Secondary/Misattributed/None)"),
                                       ["Primary", "Secondary", "Misattributed", "None"]),
            "error_types": g(r, "Error types (from taxonomy)"),
            "input_tokens": "", "output_tokens": "", "cost": "", "seconds": "",
        })
        extras.append({
            "id": rid, "model": model,
            "tester": g(r, "Tester"), "date": g(r, "Date")[:10],
            "chatbot": g(r, "Chatbot"), "model_version": g(r, "Model version"),
            "logged_in": g(r, "Logged in? (Y/N)"),
            "other_numbers": g(r, "Other numbers given"),
            "source_followup": g(r, "Source claimed (follow-up)"),
            "caveat_text": g(r, "Caveat included? (Y/N + what)"),
            "hallucination_category": g(r, "Hallucination category"),
            "screenshot": g(r, "Screenshot link"),
            "notes": g(r, "Notes"),
        })
    pd.DataFrame(results, columns=RESULTS_COLUMNS).to_csv(os.path.join(OUT, "week2_results_hand.csv"), index=False)
    pd.DataFrame(extras).to_csv(os.path.join(OUT, "week2_hand_extras.csv"), index=False)

    print(f"prompts: {len(prompts)}  key rows: {len(key_rows)}  key corrections: {len(changes)}  "
          f"result rows: {len(results)}  -> {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answer-key", required=True, help="Week 2 Answer Key .xlsx (File > Download > xlsx)")
    ap.add_argument("--results", required=True, help="Week 2 Benchmark Results .xlsx")
    a = ap.parse_args()
    export(a.answer_key, a.results)
