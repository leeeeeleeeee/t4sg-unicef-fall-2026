"""AI judge: grades sycophantic agreement, narrative distortion and pattern answers with a free model.

Usage:
    # grade a results file (run scorer.py first so the number scores exist)
    python pipeline/judge.py results/<run>/results_scored.csv --prompts prompts/ --answer-key data/answer_key.csv

    # check the judge against our 30 hand labels (data/test_set/judge_labels.csv)
    python pipeline/judge.py --validate

    # see exactly what would be sent, without calling a model
    python pipeline/judge.py --validate --dry-run
    # test the whole pipeline with a fake model (no key needed)
    python pipeline/judge.py --validate --mock

Options: --model (default: $JUDGE_MODEL or openrouter/nvidia/nemotron-3-ultra-550b-a55b:free; any LiteLLM
model name works, e.g. gemini/gemini-3.5-flash-lite), --limit N, --sleep SECONDS between calls (free tiers rate-limit).

Needs OPENROUTER_API_KEY (or GEMINI_API_KEY for gemini/ models) in .env.
Use a judge from a different model family than the model being judged.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, load_answer_key, load_dotenv_if_present, load_prompts, read_csv_str  # noqa: E402

RUBRIC_PATH = os.path.join(ROOT, "config", "judge_rubric.md")
TS = os.path.join(ROOT, "data", "test_set")
# Not a Google model: Gemini is one of the chatbots being judged. Checked working 17 Nov 2026.
DEFAULT_MODEL = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
LABELS = ["sycophantic_agreement", "narrative_distortion", "pattern_answer"]
TAXONOMY_NAME = {"sycophantic_agreement": "Sycophantic agreement",
                 "narrative_distortion": "Narrative distortion",
                 "pattern_answer": "Pattern answer"}
JUDGE_COLUMNS = ["judge_sycophantic_agreement", "judge_narrative_distortion", "judge_pattern_answer",
                 "judge_reasons", "judge_model"]


def rubric_text() -> str:
    text = open(RUBRIC_PATH, encoding="utf-8").read()
    return text.split("## Notes for us")[0].strip()  # internal notes are not sent to the model


def answer_text(row: dict, extras: dict | None) -> tuple[str, bool]:
    """The answer to judge. Week 2 rows have no transcript, so rebuild a summary from what the tester recorded."""
    if (row.get("answer") or "").strip():
        return row["answer"].strip(), False
    e = extras or {}
    parts = [f"Headline figure: {row.get('headline_number') or 'none given'}"]
    if e.get("other_numbers") and e["other_numbers"].lower() != "none":
        parts.append(f"Other figures mentioned: {e['other_numbers']}")
    parts.append(f"Year given: {row.get('year_given') or 'none'}")
    parts.append(f"Sources named: {row.get('source_claimed') or 'none'}")
    if e.get("source_followup"):
        parts.append(f"When asked for its source, it said: {e['source_followup']}")
    if e.get("caveat_text"):
        parts.append(f"Caveats (as recorded by the tester): {e['caveat_text']}")
    return "\n".join(parts), True


def build_messages(row: dict, prompt: dict, key: dict, extras: dict | None = None) -> list[dict]:
    ans, is_summary = answer_text(row, extras)
    official = key.get("unicef_value", "")
    official_txt = (f"{official} {key.get('unit', '')} ({key.get('year', '')}, {key.get('source', '')})"
                    if official else "not available")
    if key.get("range_low"):
        official_txt += f", uncertainty range {key['range_low']} to {key['range_high']}"
    if (key.get("data_exists") or "").upper() == "N":
        official_txt += ". NOTE: UNICEF has no value for the year the user asked about; the figure above is the nearest/latest"
    user = (
        f"USER QUESTION:\n{prompt.get('prompt', '(unknown)')}\n\n"
        f"OFFICIAL UNICEF VALUE: {official_txt}\n"
        f"NUMBER SCORE ALREADY ASSIGNED: {row.get('number_score') or 'n/a'}\n\n"
        + ("CHATBOT ANSWER (a SUMMARY recorded by a human tester, not the full transcript):\n" if is_summary
           else "CHATBOT ANSWER:\n")
        + ans + "\n\nGrade the three labels. Return only the JSON."
    )
    return [{"role": "system", "content": rubric_text()}, {"role": "user", "content": user}]


def parse_judgement(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(f"no JSON in judge reply: {text[:200]!r}")
    data = json.loads(m.group(0))
    out = {}
    for lab in LABELS:
        v = str(data.get(lab, "")).strip().upper()
        out[lab] = v if v in ("Y", "N", "NA") else ""
    out["reasons"] = " | ".join(f"{k.split('_')[0]}: {data.get(k, '')}" for k in
                                ("sycophantic_reason", "narrative_reason", "pattern_reason") if data.get(k))
    return out


MOCK_REPLY = json.dumps({"sycophantic_agreement": "N", "sycophantic_reason": "mock",
                         "narrative_distortion": "N", "narrative_reason": "mock",
                         "pattern_answer": "N", "pattern_reason": "mock"})


def call_judge(messages: list[dict], model: str, mock: bool = False, retries: int = 3) -> tuple[dict, dict]:
    import litellm
    litellm.suppress_debug_info = True
    litellm.drop_params = True  # some models (e.g. Gemini 3.x) reject settings like temperature
    last = None
    for attempt in range(retries):
        try:
            kwargs = dict(model=model, messages=messages, temperature=0, max_tokens=600)
            if mock:
                kwargs["mock_response"] = MOCK_REPLY
            resp = litellm.completion(**kwargs)
            text = resp.choices[0].message.content
            usage = getattr(resp, "usage", None)
            try:
                cost = litellm.completion_cost(completion_response=resp) if not mock else 0.0
            except Exception:
                cost = 0.0
            meta = {"input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                    "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0, "cost": cost or 0.0}
            return parse_judgement(text), meta
        except Exception as e:  # rate limits on free tiers are common: back off and retry
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"judge failed after {retries} tries: {last}")


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    cats = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def judge_rows(rows: list[dict], prompts: dict, key: dict, extras: dict, args) -> list[dict]:
    out = []
    total_cost = 0.0
    for i, r in enumerate(rows):
        msgs = build_messages(r, prompts.get(r["id"], {}), key.get(r["id"], {}), extras.get((r["id"], r["model"])))
        if args.dry_run:
            if i == 0:
                print("=" * 30, "SYSTEM", "=" * 30, "\n" + msgs[0]["content"][:600], "...\n")
            print("=" * 30, f"USER ({r['id']} / {r['model']})", "=" * 30, "\n" + msgs[1]["content"] + "\n")
            continue
        j, meta = call_judge(msgs, args.model, mock=args.mock)
        total_cost += meta["cost"]
        out.append({**r, **{f"judge_{k}": j[k] for k in LABELS}, "judge_reasons": j["reasons"],
                    "judge_model": args.model + (" (mock)" if args.mock else ""),
                    "judge_input_tokens": meta["input_tokens"], "judge_output_tokens": meta["output_tokens"],
                    "judge_cost": meta["cost"]})
        print(f"[{i + 1}/{len(rows)}] {r['id']:6} {r['model'][:28]:28} "
              + " ".join(f"{k.split('_')[0][:4]}={j[k] or '?'}" for k in LABELS))
        if args.sleep and i < len(rows) - 1:
            time.sleep(args.sleep)
    if out:
        print(f"judge cost: ${total_cost:.4f}")
    return out


def validate(args) -> None:
    labels = read_csv_str(os.path.join(TS, "judge_labels.csv"))
    hand = read_csv_str(os.path.join(TS, "week2_results_hand.csv"))
    ex = read_csv_str(os.path.join(TS, "week2_hand_extras.csv"))
    extras = {(r["id"], r["model"]): r for r in ex.to_dict("records")}
    prompts = load_prompts([os.path.join(TS, "week2_prompts.csv")])
    key = load_answer_key(os.path.join(TS, "week2_answer_key.csv"))
    merged = labels.merge(hand, on=["id", "model"], how="left", suffixes=("_label", ""))
    missing = merged[merged["answer"].isna()]
    if len(missing):
        sys.exit(f"labels not found in week2_results_hand.csv: {missing[['id', 'model']].values.tolist()}")
    rows = merged.to_dict("records")[: args.limit or None]
    judged = judge_rows(rows, prompts, key, extras, args)
    if args.dry_run:
        return
    res = pd.DataFrame(judged)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    res_path = os.path.join(ROOT, "reports", "judge_validation_rows.csv")
    keep = ["id", "model", "confidence"] + [c for lab in LABELS for c in (lab, f"judge_{lab}")] + ["judge_reasons", "evidence"]
    res[keep].to_csv(res_path, index=False)

    lines = [f"# AI judge vs our hand labels", "",
             f"Judge model: `{args.model}`{' (MOCK: fake replies, numbers are meaningless)' if args.mock else ''}. "
             f"Rows: {len(res)} (from `data/test_set/judge_labels.csv`). "
             f"Labels confirmed by a person: {int((labels['confirmed_by'] != '').sum())} of {len(labels)}.", "",
             "The judge only saw a summary of each answer that the tester recorded (no transcripts were saved in "
             "Week 2), so this is a lower bound on how well it does with full answers.", "",
             "| Label | Agreement | Cohen's kappa | Hand Y | Judge Y | Judge caught (of hand Y) |", "|---|---|---|---|---|---|"]
    for lab in LABELS:
        sub = res[res[lab].isin(["Y", "N", "NA"])]
        a, b = sub[lab].tolist(), sub[f"judge_{lab}"].tolist()
        agree = sum(x == y for x, y in zip(a, b))
        k = cohen_kappa(a, b)
        hand_y = a.count("Y")
        caught = sum(1 for x, y in zip(a, b) if x == "Y" and y == "Y")
        lines.append(f"| {TAXONOMY_NAME[lab]} | {agree}/{len(a)} ({agree / max(len(a), 1):.0%}) | "
                     f"{'n/a' if k is None else f'{k:.2f}'} | {hand_y} | {b.count('Y')} | {caught}/{hand_y} |")
    lines += ["", "Kappa guide: below 0.2 poor, 0.2-0.4 fair, 0.4-0.6 moderate, 0.6-0.8 substantial, above 0.8 near-perfect.",
              "", "## Disagreements", "", "| ID | Model | Label | Hand | Judge | Judge's reason | Our evidence |",
              "|---|---|---|---|---|---|---|"]
    for r in res.to_dict("records"):
        for lab in LABELS:
            if r[lab] != r[f"judge_{lab}"]:
                lines.append(f"| {r['id']} | {r['model']} | {TAXONOMY_NAME[lab]} | {r[lab]} | {r[f'judge_{lab}']} | "
                             f"{(r['judge_reasons'] or '')[:160]} | {r['evidence'][:120]} |")
    path = os.path.join(ROOT, "reports", "judge_agreement.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[8:8 + 2 + len(LABELS)]))
    print(f"-> {path}\n-> {res_path}")


def grade_file(args) -> None:
    df = read_csv_str(args.results)
    prompts = load_prompts(args.prompts)
    key = load_answer_key(args.answer_key)
    rows = df.to_dict("records")[: args.limit or None]
    judged = judge_rows(rows, prompts, key, {}, args)
    if args.dry_run:
        return
    out = pd.DataFrame(judged)
    for i, r in out.iterrows():
        errs = [] if r.get("error_types", "") in ("", "None") else str(r["error_types"]).split("; ")
        for lab in LABELS:
            if r[f"judge_{lab}"] == "Y" and TAXONOMY_NAME[lab] not in errs:
                errs.append(TAXONOMY_NAME[lab])
        out.at[i, "error_types"] = "; ".join(errs) if errs else "None"
    path = args.out or re.sub(r"(_scored)?\.csv$", "", args.results) + "_judged.csv"
    out.to_csv(path, index=False)
    print(f"-> {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", nargs="?", help="scored results CSV to grade")
    ap.add_argument("--validate", action="store_true", help="compare the judge with data/test_set/judge_labels.csv")
    ap.add_argument("--prompts", nargs="+", default=[os.path.join(ROOT, "prompts")])
    ap.add_argument("--answer-key", default=os.path.join(ROOT, "data", "answer_key.csv"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between calls (Gemini free tier ~15/min)")
    ap.add_argument("--dry-run", action="store_true", help="print the judge prompts; call nothing")
    ap.add_argument("--mock", action="store_true", help="use a fake model reply (tests the pipeline, no key)")
    args = ap.parse_args()
    load_dotenv_if_present()
    args.model = args.model or os.getenv("JUDGE_MODEL") or DEFAULT_MODEL
    if args.mock:
        args.sleep = 0
    if args.validate:
        validate(args)
    elif args.results:
        grade_file(args)
    else:
        ap.error("give a results file or --validate")


if __name__ == "__main__":
    main()
