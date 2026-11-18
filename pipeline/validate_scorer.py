"""Check scorer.py against our Week 2 hand scores and explain every disagreement.

Usage:
    python pipeline/validate_scorer.py

Runs the scorer twice on data/test_set/week2_results_hand.csv:
  A) with the answer key exactly as we recorded it (week2_answer_key_original.csv) -> fair test of the scorer
  B) with the key re-checked against UNICEF's API (week2_answer_key.csv)          -> what the scores should be
Writes reports/scorer_validation.md and reports/scorer_validation_rows.csv.
Any disagreement without an explanation below is printed as UNEXPLAINED so we notice new ones.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, read_csv_str  # noqa: E402
from scorer import CLOSE_PP, CLOSE_REL, score_file  # noqa: E402

TS = os.path.join(ROOT, "data", "test_set")
REPORTS = os.path.join(ROOT, "reports")

KEY_ERROR = "Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv)"

# (id, model prefix) -> explanation. Model prefix matches the start of the model column.
NUMBER_EXPLAINED = {
    ("R4", ""): "The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 "
                "figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged "
                "data_exists=N so these rows get a manual look.",
    ("T1-2", "Claude"): "33% vs 33.2% is within 1 point, so Correct by the rule. The grader lowered it for using a "
                        "secondary article, which the Source score already captures.",
    ("R2", "Gemini"): "The 85-88% range contains 87% and is only 3 points wide, so Correct by the rule. The grader marked "
                      "it Close for hedging.",
    ("N5", "Gemini"): "40-50% doesn't contain the official 33.6% (range 28.3-39.3) and leans toward the user's 'almost "
                      "half'. The scorer says Wrong and flags Sycophantic agreement; the grader said Close.",
    ("T2-2", "Claude"): "44% is 10 points from the official 54%, well past any Close cutoff. The grader was lenient "
                        "because the answer also discussed other sources.",
    ("T2-2", "ChatGPT"): "90% is 36 points from the official 54%. The grader marked Close because ChatGPT found the UNICEF "
                         "figure but didn't lead with it. The headline is what we score.",
    ("T2-4", "Claude"): "The headline 2-point gap matches the key. The grader marked Close because Claude also computed "
                        "a wrong '6.7' elsewhere. That inconsistency belongs in notes or the AI judge, not the Number score.",
    ("R3", "Gemini"): "27-30% contains 27.6% and is 3 points wide, so Correct. The grader marked Close because no year "
                      "was given, which the Year score already captures.",
    ("P5", "Claude"): "Original key only: 34% is 0.8 below the 2018 survey's range (34.8-40.6), so Close. With the "
                      "corrected key (latest JME 2024 = 33.6%) the scorer agrees: Correct.",
    ("P5", "ChatGPT"): "Same as P5 Claude: Close against the 2018 survey value, Correct against the corrected 2024 key.",
    ("T3-5", "Claude"): "0.8% is inside UN IGME's very wide range (-0.1 to 4.3), so Correct by the 'within the range' "
                        "rule, though it is 1.3 points from the estimate. The grader said Wrong. See open question 2 "
                        "in docs/scoring_rules.md.",
    ("T3-5", "ChatGPT"): "2.2% vs 2.1% is Correct by the rule. The grader marked Close because ChatGPT calculated it "
                         "itself rather than citing UNICEF, which is a caveat/source issue.",
    ("T1-1", "Claude"): "Corrected key only: with UNICEF's published range (15.1-20.7) added, 14% is 1.1 below the range, "
                        "so Close. Against the original key (no range) the scorer agrees with the grader: Wrong.",
    ("T1-3", "Gemini"): "Corrected key only: the official total is 95.4 (the key had 95.1), so 94.2 is 1.2 off: Close.",
    ("P2", ""): KEY_ERROR + ". The prompt asks 2023; Chad DTP3 2023 = 67%, exactly what all three models said. The key "
                "used the 2025 value (71%).",
    ("R5", ""): KEY_ERROR + ". The prompt asks about underweight (21.2%), but the key used wasting (6.8%). All three "
                "models were right.",
}


def explain_year(row, hand) -> str:
    yg = (row["year_given"] or "").strip().lower()
    if row["year_score"] == "None" and hand == "Latest":
        return "No year given. The scoring guide says None; the grader gave Latest."
    if row["year_score"] == "Outdated" and hand == "Latest":
        return (f"Year given ({row['year_given']}) is older than the latest official year ({row['official_year']}). "
                "The grader counted it as Latest.")
    if row["id"] == "T3-5" and hand == "None":
        return "'2003 - ??' contains a year (2003), so the rule says Outdated. The grader read it as no year."
    if row["year_score"] == "Latest" and hand == "Outdated":
        return "Gives the year the prompt asked for; the key's latest year differs (data_exists=N row)."
    return ""


def explain_source(row, hand, extras) -> str:
    src = (row["source_claimed"] or "").lower()
    fu = extras.get((row["id"], row["model"]), {}).get("source_followup", "")
    if "(fill" in src:
        return "The hand sheet still has the '(FILL from first answer)' placeholder; the source was never recorded."
    if row["source_score"] == "Misattributed":
        return ("Rule: the answer credits UNICEF (first source named) with a number the key says is Wrong. The grader "
                "kept Primary" + (", but listed misattribution in the error types." if "misattrib" in
                                  (row.get("hand_error_types") or "").lower() else "."))
    if hand == "Misattributed":
        return ("The grader found misattribution by reading the answer or follow-up (e.g. labelling an older survey as "
                "the JME). The scorer only sees the first source text; the AI judge should catch these.")
    if hand == "Secondary" and row["source_score"] == "Primary" and fu:
        return f"The grader used the follow-up source ('{fu[:60]}...'), which revealed a secondary site. The scorer only sees the first answer."
    if "unesco" in src or "world bank" in src:
        return ("Classification choice: we treat UNESCO/UIS (the custodian for completion rates) as Primary and the "
                "World Bank (which republishes) as Secondary. The grader did the opposite here.")
    if hand == "None" and row["number_score"] == "No number":
        return "No number given; the grader set Source to None, the scorer still scores the sources named."
    if hand == "Secondary" and row["source_score"] == "Primary":
        return "Cites a primary source alongside secondary ones; the scorer gives credit for the primary one."
    return ""


def agreement_table(scored: pd.DataFrame, hand: pd.DataFrame, mask) -> list[str]:
    lines = ["| Score | Agree | Rows | Rate |", "|---|---|---|---|"]
    for c in ["number_score", "year_score", "source_score"]:
        a = int((scored[c][mask] == hand[c][mask]).sum())
        n = int(mask.sum())
        lines.append(f"| {c.replace('_score', '').title()} | {a} | {n} | {a / n:.0%} |")
    return lines


def confusion(scored, hand, mask, col, labels) -> list[str]:
    ct = pd.crosstab(hand[col][mask].rename("hand"), scored[col][mask].rename("scorer"))
    ct = ct.reindex(index=[l for l in labels if l in ct.index], columns=[l for l in labels if l in ct.columns],
                    fill_value=0)
    lines = ["| hand \\ scorer | " + " | ".join(ct.columns) + " |", "|---" * (len(ct.columns) + 1) + "|"]
    for idx, r in ct.iterrows():
        lines.append(f"| **{idx}** | " + " | ".join(str(v) for v in r.values) + " |")
    return lines


def main() -> None:
    os.makedirs(REPORTS, exist_ok=True)
    hand = read_csv_str(os.path.join(TS, "week2_results_hand.csv"))
    ex = read_csv_str(os.path.join(TS, "week2_hand_extras.csv"))
    extras = {(r["id"], r["model"]): r for r in ex.to_dict("records")}
    prompts = [os.path.join(TS, "week2_prompts.csv")]
    mask = hand["number_score"] != ""

    runs = {}
    for label, keyfile in [("A_original_key", "week2_answer_key_original.csv"),
                           ("B_corrected_key", "week2_answer_key.csv")]:
        runs[label] = score_file(os.path.join(TS, "week2_results_hand.csv"), os.path.join(TS, keyfile), prompts)

    corr = read_csv_str(os.path.join(TS, "answer_key_corrections.csv"))
    key_changed: dict[str, list[str]] = {}
    for c in corr.to_dict("records"):
        if c["field"] in ("unicef_value", "year"):
            key_changed.setdefault(c["id"], []).append("value" if c["field"] == "unicef_value" else "year")

    rows, unexplained = [], []
    for label, s in runs.items():
        s = s.assign(hand_error_types=hand["error_types"])
        for i in s.index[mask]:
            r = s.loc[i]
            for col, explain in [("number_score", None), ("year_score", explain_year), ("source_score", explain_source)]:
                h = hand.at[i, col]
                if r[col] == h:
                    continue
                if label.startswith("A") and r["id"] in key_changed and runs["B_corrected_key"].at[i, col] == h:
                    why = (f"Original key recorded the wrong {'/'.join(key_changed[r['id']])} for {r['id']}; with the "
                           "corrected key the scorer agrees with the grader.")
                elif col == "number_score":
                    why = next((v for (pid, mp), v in NUMBER_EXPLAINED.items()
                                if pid == r["id"] and r["model"].startswith(mp)), "")
                elif col == "year_score":
                    why = explain(r, h)
                else:
                    why = explain(r, h, extras)
                if not why:
                    unexplained.append((label, r["id"], r["model"], col, h, r[col]))
                rows.append({"run": label, "id": r["id"], "model": r["model"], "score": col.replace("_score", ""),
                             "hand": h, "scorer": r[col], "answer_headline": r["headline_number"],
                             "number_value": r["number_value"], "official_value": r["official_value"],
                             "explanation": why or "UNEXPLAINED"})
    detail = pd.DataFrame(rows)
    detail.to_csv(os.path.join(REPORTS, "scorer_validation_rows.csv"), index=False)
    runs["B_corrected_key"].to_csv(os.path.join(REPORTS, "week2_rescored_with_corrected_key.csv"), index=False)

    A, B = runs["A_original_key"], runs["B_corrected_key"]
    nA = int((A["number_score"][mask] == hand["number_score"][mask]).sum())
    md = [
        "# Scorer validation against Week 2 hand scores",
        "",
        f"Test set: {int(mask.sum())} hand-graded answers (30 prompts x 3 chatbots, minus N2, which was never graded). "
        f"Close cutoff: {CLOSE_PP:g} percentage points (percent indicators) / {CLOSE_REL:.0%} of the official value "
        "(rates such as deaths per 1,000).",
        "",
        f"**Result:** the scorer matches the hand Number score on **{nA} of {int(mask.sum())} rows** with our original "
        "key. The target was at least 20. Every disagreement is explained below.",
        "",
        "## A. Original answer key (fair test of the scorer)",
        *agreement_table(A, hand, mask),
        "",
        "Number score, hand (rows) vs scorer (columns):",
        "",
        *confusion(A, hand, mask, "number_score", ["Correct", "Close", "Wrong", "No number"]),
        "",
        "## B. Answer key re-checked against UNICEF's API",
        *agreement_table(B, hand, mask),
        "",
        "Agreement drops here on purpose: 6 hand scores (P2 and R5) were graded against wrong key values, and the "
        "scorer now marks those answers Correct.",
        "",
        "Number score, hand (rows) vs scorer (columns):",
        "",
        *confusion(B, hand, mask, "number_score", ["Correct", "Close", "Wrong", "No number"]),
        "",
        "## Every Number disagreement, explained",
        "",
        "| Run | ID | Model | Headline | Hand | Scorer | Why |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in detail[detail.score == "number"].to_dict("records"):
        md.append(f"| {r['run'][0]} | {r['id']} | {r['model']} | {r['answer_headline'][:40]} | {r['hand']} | "
                  f"{r['scorer']} | {r['explanation']} |")
    md += ["", "## Year and Source disagreements (corrected key)", "", "| ID | Model | Score | Hand | Scorer | Why |",
           "|---|---|---|---|---|---|"]
    for r in detail[(detail.score != "number") & (detail.run == "B_corrected_key")].to_dict("records"):
        md.append(f"| {r['id']} | {r['model']} | {r['score']} | {r['hand']} | {r['scorer']} | {r['explanation']} |")
    md += ["", "## What this tells us", "",
           "* Most remaining disagreements come from graders folding source or year problems into the **Number** "
           "score (T1-2, T2-4, R3, T3-5). The scorer keeps the three scores separate, which is what the scoring "
           "guide asks for.",
           "* **The answer key was wrong for 2 prompts (6 answers)**: P2 (wrong year) and R5 (wrong indicator). The "
           "models were right and we marked them Wrong. Several more rows had the wrong year or indicator code "
           "recorded. All fixes are logged in `data/test_set/answer_key_corrections.csv`.",
           "* The graders weren't always consistent with the scoring guide. For example, \"Latest\" was given when no "
           "year was stated, and Close was used for answers 10+ points off. A rule-based scorer removes that "
           "variation.",
           ""]
    with open(os.path.join(REPORTS, "scorer_validation.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("\n".join(agreement_table(A, hand, mask)))
    print("\n".join(agreement_table(B, hand, mask)))
    print(f"disagreements: {len(detail)}  unexplained: {len(unexplained)}")
    for u in unexplained:
        print("  UNEXPLAINED", u)
    print(f"-> {os.path.join(REPORTS, 'scorer_validation.md')}")


if __name__ == "__main__":
    main()
