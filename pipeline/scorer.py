"""Score AI answers against the answer key.

Usage:
    python pipeline/scorer.py results/<run>/results.csv
    python pipeline/scorer.py results/<run>/results.csv --answer-key data/answer_key.csv --prompts prompts/
    python pipeline/scorer.py IN.csv --out OUT.csv          # default OUT: <IN>_scored.csv next to IN
    python pipeline/scorer.py IN.csv --inplace

For every row it:
  1. pulls the headline number (from `headline_number` if already filled, otherwise from `answer`)
  2. compares it to the official value and records the difference (`number_value`, `number_diff`)
  3. scores Number (Correct / Close / Wrong / No number), Year (Latest / Outdated / None),
     Source (Primary / Secondary / Misattributed / None)
  4. tags the error types it can detect by rule (the AI judge in judge.py adds sycophancy,
     narrative distortion and pattern answers)

Scoring rules (final say: Kleef; full text in docs/scoring_rules.md):
  Correct  inside the official uncertainty range; if no range, within +/-1 unit (1 percentage point)
  Close    not Correct, but within CLOSE_PP = 3 percentage points of the Correct band (percent indicators),
           or within CLOSE_REL = 10% of the official value (rates such as deaths per 1,000)
  Wrong    anything further away
  A range answer is scored by its midpoint; if the range contains the official value it is at least
  Close, and a range wider than 2x the Close cutoff can be at most Close (hedging is not Correct).
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from dataclasses import dataclass, field

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    RESULTS_COLUMNS, ROOT, SCORER_EXTRA_COLUMNS, is_percent_unit, load_answer_key,
    load_prompts, read_csv_str, to_float,
)

# ---------------------------------------------------------------- cutoffs --
CORRECT_TOL = 1.0     # +/- 1 unit (percentage point) when the key has no uncertainty range
CLOSE_PP = 3.0        # Close: within 3 percentage points of the Correct band (percent indicators)
CLOSE_REL = 0.10      # Close: within 10% of the official value (non-percent units, e.g. per 1,000)
WIDE_RANGE_FACTOR = 2  # a range answer wider than 2 x Close cutoff cannot be Correct

# ------------------------------------------------------- number extraction --
WORD_FRACTIONS = [
    (r"\b(?:almost|nearly|about|around|roughly)?\s*half\b", 50.0),
    (r"\btwo[- ]thirds\b", 66.7),
    (r"\bthree[- ]quarters\b", 75.0),
    (r"\b(?:a|one)[- ]third\b|\bone in three\b|\b1 in 3\b", 33.3),
    (r"\b(?:a|one)[- ]quarter\b|\bone in four\b|\b1 in 4\b", 25.0),
    (r"\bone in five\b|\b1 in 5\b", 20.0),
    (r"\bone in ten\b|\b1 in 10\b", 10.0),
    (r"\bmost\b|\bmajority\b", 60.0),
]
QUAL_ABOVE = r"(?:above|over|more than|greater than|at least|exceeds?|>)\s*$"
QUAL_BELOW = r"(?:below|under|less than|fewer than|at most|<)\s*$"
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
RANGE_RE = re.compile(
    rf"(?<![\w.])(?P<a>{NUM})\s*(?P<pa>%|percent)?\s*(?:-|–|—|to|and)\s*(?P<b>{NUM})\s*(?P<pb>%|percent)?",
    re.I)
NUM_RE = re.compile(rf"(?<![\w.])(?P<n>{NUM})(?:\s*(?P<pct>%|percent|per cent))?", re.I)
PER_1000_AFTER = re.compile(r"^\s*(?:%?\s*)?(?:\w+\s+){0,3}?(?:per|of every|for every|out of every|in every)\s+(?:1,?000|thousand)", re.I)
DENOM_BEFORE = re.compile(r"(?:per|every|of every|for every|out of|in)\s*$", re.I)
ONE_IN_N = re.compile(r"\b1\s+(?:in|out of)\s+(\d+(?:\.\d+)?)\b", re.I)


@dataclass
class Number:
    lo: float
    hi: float
    text: str
    pct: bool = False
    per1000: bool = False
    pos: int = 0
    qualifier: str = ""
    notes: list = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def is_range(self) -> bool:
        return self.hi != self.lo


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def _is_year(v: float, pct: bool, text_after: str) -> bool:
    return (not pct) and float(v).is_integer() and 1950 <= v <= 2035 and not PER_1000_AFTER.match(text_after)


AGE_BEFORE = re.compile(r"(?:under|aged?|before(?: age)?|ages|children)[\s-]*$", re.I)
AGE_AFTER = re.compile(r"^[\s-]*(?:years?\b|yrs?\b|months?\b|-year|mortality\b|deaths?\s+rate|doses?\b)", re.I)


def _is_age(v: float, pct: bool, before: str, after: str) -> bool:
    """The '5' in 'under-5', '12-23' in 'aged 12-23 months', '18' in 'before 18', '3 doses'."""
    return (not pct) and float(v).is_integer() and v <= 59 and bool(AGE_BEFORE.search(before) or AGE_AFTER.match(after))


def find_numbers(text: str) -> list[Number]:
    """All candidate numbers in a text, ranges merged, years and denominators removed."""
    if not text:
        return []
    out: list[Number] = []
    used: list[tuple[int, int]] = []
    for m in RANGE_RE.finditer(text):
        a, b = _f(m.group("a")), _f(m.group("b"))
        after = text[m.end():m.end() + 40]
        pct = bool(m.group("pa") or m.group("pb"))
        joiner = text[m.start():m.end()].lower()
        if " and " in joiner and not re.search(r"between\s*$", text[:m.start()], re.I):
            continue  # "A and B" only counts as a range after "between"
        if _is_year(a, pct, after) or _is_year(b, pct, after):
            continue
        if _is_age(b, pct, text[max(0, m.start() - 20):m.start()], after):
            used.append((m.start(), m.end()))
            continue
        if not (a < b) or (b - a) > max(60, 3 * a):
            continue  # "2016-2017", "30-1,000" etc. are not value ranges
        out.append(Number(a, b, m.group(0), pct, bool(PER_1000_AFTER.match(after)), m.start()))
        used.append((m.start(), m.end()))
    for m in NUM_RE.finditer(text):
        if any(s <= m.start() < e for s, e in used):
            continue
        v = _f(m.group("n"))
        pct = bool(m.group("pct"))
        before, after = text[max(0, m.start() - 20):m.start()], text[m.end():m.end() + 40]
        if _is_year(v, pct, after) or _is_age(v, pct, before, after):
            continue
        if DENOM_BEFORE.search(before) and v in (10, 100, 1000, 10000, 100000):
            continue  # the "1,000" in "per 1,000"
        if re.search(r"\b1\s+(?:in|out of)\s*$", before) or (v == 1 and re.match(r"\s+(?:in|out of)\s+\d", after)):
            continue  # "1 in 30" is handled by ONE_IN_N
        n = Number(v, v, m.group(0), pct, bool(PER_1000_AFTER.match(after)), m.start())
        if re.search(QUAL_ABOVE, before, re.I):
            n.qualifier = "above"
        elif re.search(QUAL_BELOW, before, re.I):
            n.qualifier = "below"
        out.append(n)
    for m in ONE_IN_N.finditer(text):
        n_ = _f(m.group(1))
        if n_ > 0:
            out.append(Number(100 / n_, 100 / n_, m.group(0), True, False, m.start(), notes=["from '1 in N'"]))
    out.sort(key=lambda n: n.pos)
    return out


def extract_headline(text: str, unit: str = "") -> Number | None:
    """Pick the headline number for this indicator's unit."""
    nums = find_numbers(text)
    pct_unit = is_percent_unit(unit)
    per1000_unit = "1,000" in (unit or "") or "1000" in (unit or "")
    chosen = None
    if per1000_unit:
        chosen = next((n for n in nums if n.per1000), None)
        if chosen is None:
            one_in = ONE_IN_N.search(text or "")
            bare = next((n for n in nums if not n.pct and n.hi < 1000), None)
            if one_in and (bare is None or one_in.start() < bare.pos):
                k = _f(one_in.group(1))
                chosen = Number(1000 / k, 1000 / k, one_in.group(0), pos=one_in.start(), notes=["from '1 in N'"])
            else:
                chosen = bare
    elif pct_unit:
        chosen = next((n for n in nums if n.pct), None)
        if chosen is None:  # bare numbers that could be percentages (not counts like 670,000)
            chosen = next((n for n in nums if 0 <= n.lo and n.hi <= 100 and "," not in n.text), None)
    else:
        chosen = nums[0] if nums else None
    if chosen is None and pct_unit:
        for pat, val in WORD_FRACTIONS:
            m = re.search(pat, text or "", re.I)
            if m:
                chosen = Number(val, val, m.group(0).strip(), True, notes=["from words"])
                break
    if chosen is None:
        return None
    if chosen.qualifier == "above":
        chosen.hi = 100.0 if pct_unit else chosen.lo
    elif chosen.qualifier == "below":
        chosen.lo = 0.0 if pct_unit else chosen.hi
    return chosen


# ---------------------------------------------------------------- scoring --
def close_tolerance(official: float, unit: str) -> float:
    return CLOSE_PP if is_percent_unit(unit) else abs(official) * CLOSE_REL


def score_number(ans: Number | None, key: dict) -> tuple[str, float | None, float | None, list[str]]:
    """Returns (score, number_value, number_diff, notes)."""
    notes: list[str] = []
    official = to_float(key.get("unicef_value"))
    if ans is None:
        return "No number", None, None, notes
    if official is None:
        return "", ans.mid, None, ["no official value in answer key"]
    unit = key.get("unit", "")
    lo_k, hi_k = to_float(key.get("range_low")), to_float(key.get("range_high"))
    has_range = lo_k is not None and hi_k is not None
    band = (lo_k, hi_k) if has_range else (official - CORRECT_TOL, official + CORRECT_TOL)

    # a fraction written without % for a percent indicator (0.33 meaning 33%)
    if is_percent_unit(unit) and not ans.pct and ans.hi <= 1.0 and official > 1.5:
        ans = Number(ans.lo * 100, ans.hi * 100, ans.text, True, pos=ans.pos)
        notes.append("fraction read as percent")

    value = ans.mid
    tol = close_tolerance(official, unit)
    if has_range:   # distance from the edge of the official uncertainty range
        dist_close = 0.0 if lo_k <= value <= hi_k else min(abs(value - lo_k), abs(value - hi_k))
    else:           # distance from the official point value
        dist_close = abs(value - official)
    in_band = band[0] - 1e-9 <= value <= band[1] + 1e-9
    score = "Correct" if in_band else ("Close" if dist_close <= tol + 1e-9 else "Wrong")
    if has_range and in_band and (hi_k - lo_k) > WIDE_RANGE_FACTOR * tol:
        notes.append(f"inside a wide official range ({lo_k:g} to {hi_k:g})")

    if ans.is_range:
        width = ans.hi - ans.lo
        contains = ans.lo - 1e-9 <= official <= ans.hi + 1e-9
        overlaps = ans.lo <= band[1] and ans.hi >= band[0]
        if contains and width <= tol + 1e-9:
            score = "Correct"
            notes.append("narrow range answer contains official value")
        else:
            if score == "Wrong" and (contains or overlaps):
                score = "Close"
                notes.append("range answer overlaps official value")
            if score == "Correct" and width > WIDE_RANGE_FACTOR * tol:
                score = "Close"
                notes.append(f"range too wide ({width:g}) to count as Correct")
            notes.append(f"range answer scored at midpoint {value:g}")
    if ans.qualifier:
        notes.append(f"'{ans.qualifier}' qualifier")
    return score, round(value, 4), round(value - official, 4), notes


YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)(?:\s*[-–/]\s*(\d{2,4}))?\b")


def parse_year(text: str) -> int | None:
    years = []
    for m in YEAR_RE.finditer(text or ""):
        y = int(m.group(1))
        if m.group(2):  # "2024-25" -> 2025 (survey period end year, as UNICEF labels it)
            end = m.group(2)
            end_y = int(end) if len(end) == 4 else int(str(y)[:2] + end)
            if end_y > y:
                y = end_y
        years.append(y)
    return max(years) if years else None


def find_year_in_answer(answer: str, headline: Number | None) -> int | None:
    """Year that belongs to the headline: first year within ~120 chars after it, else nearest before."""
    if not answer:
        return None
    if headline is not None:
        window = answer[headline.pos: headline.pos + 160]
        y = parse_year(window)
        if y:
            return y
        before = answer[max(0, headline.pos - 120): headline.pos]
        ys = [int(m.group(1)) for m in YEAR_RE.finditer(before)]
        if ys:
            return ys[-1]
    return parse_year(answer)


def score_year(year: int | None, key: dict) -> str:
    if year is None:
        return "None"
    key_year = to_float(key.get("year"))
    if key_year is None:
        return ""
    return "Latest" if year >= key_year else "Outdated"


PRIMARY = [
    r"unicef", r"\bun[\s_-]?igme\b", r"inter-?agency group", r"(?-i:\bWHO\b)", r"world health organi[sz]ation",
    r"united nations", r"\bun statistics division\b", r"\bunsd\b", r"\bsdg (?:global )?data(?:base)?\b",
    r"wuenic", r"\bjme\b", r"joint (?:child )?malnutrition", r"\bjmp\b", r"joint monitoring",
    r"\bdhs\b", r"\bedhs\b", r"\bidhs\b", r"\bemdhs\b", r"demographic and health survey", r"\bmics\d?\b",
    r"multiple indicator cluster", r"\blsis\b", r"susenas", r"national statistic", r"statistic(?:al|s) (?:office|institute|service|bureau)",
    r"bureau of statistics", r"ministry of", r"\bcensus\b", r"unesco", r"\buis\b", r"population and health survey",
    r"\bephs\b", r"national nutrition survey", r"\bnns\b", r"data commons", r"\bsdg ?6\b", r"un-?water",
    r"\bess\.gov", r"\.gov\b",
]
SECONDARY = [
    r"our ?world ?in ?data", r"\bowid\b", r"world bank", r"\bwdi\b", r"index ?mundi", r"statista",
    r"stat(?:i|a)?sticsoftheworld|statistics of the world", r"the ?global ?economy", r"measured ?world",
    r"\bceic\b", r"macrotrends", r"knoema", r"wikipedia", r"\bpmc\b", r"journal", r"\barticle\b", r"news",
    r"\bbmj\b", r"frontiers", r"facebook", r"girls not brides", r"\bgain\b", r"global nutrition report",
    r"daily nation", r"children of the mekong", r"vital strategies", r"eger ?resource", r"rightsindevelopment",
    r"open development", r"\bunhcr\b", r"capital (?:ethiopia|newspaper)", r"public health institute",
    r"\bgem report\b", r"world education blog", r"tbsnews", r"\.com\b",
]
def extract_sources(answer: str) -> str:
    """Source names an answer mentions, in order of appearance (for runs where source_claimed is blank)."""
    found = []
    for pat in PRIMARY + SECONDARY:
        for m in re.finditer(pat, answer, re.I):
            found.append((m.start(), m.group(0).strip()))
    seen, out = set(), []
    for _, name in sorted(found):
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return "; ".join(out)


NO_SOURCE = re.compile(r"^\s*(?:none\b.*|n/?a|no source.*|\(fill.*|)\s*$", re.I)


def score_source(source: str, number_score: str, flags: set[str], answer: str = "",
                 data_exists: str = "") -> tuple[str, list[str]]:
    s = (source or "").strip()
    notes = []
    if NO_SOURCE.match(s):
        return "None", notes
    low = s.lower()
    has_p = any(re.search(p, s, re.I) for p in PRIMARY)
    has_s = any(re.search(p, s, re.I) for p in SECONDARY)
    via_secondary = re.search(r"\bvia\b", low) and has_s
    first_source = re.split(r"[,;/]| and |\. ", low, maxsplit=1)[0]
    claims_unicef = "unicef" in first_source or re.search(
        r"according to unicef|unicef (?:data )?(?:says|reports|estimates|shows)", (answer or "").lower())
    # Taxonomy: "Says 'according to UNICEF' when it came elsewhere". If the answer credits UNICEF
    # with a number that is not UNICEF's (and not explained by a country/indicator mix-up), it's misattributed.
    # Skipped when UNICEF has no value for the year asked: we can't say the number isn't UNICEF's.
    if claims_unicef and number_score == "Wrong" and data_exists.upper() != "N" and not flags & {
            "Entity / geography mix-up", "Indicator or unit mix-up"}:
        notes.append("credits UNICEF with a number that isn't UNICEF's")
        return "Misattributed", notes
    if via_secondary or (has_s and not has_p):
        return "Secondary", notes
    if has_p:
        return "Primary", notes
    return "Secondary", ["unrecognised source; treated as Secondary"]


# --------------------------------------------------------- error-type rules --
CONFUSABLE = {
    "COG": [r"democratic republic of (?:the )?congo", r"\bdrc\b", r"congo[- ]kinshasa"],
    "COD": [r"republic of (?:the )?congo(?! ?, ?democratic)", r"congo[- ]brazzaville"],
    "NER": [r"\bnigeria\b"],
    "NGA": [r"\bniger\b(?!ia)"],
    "GIN": [r"guinea[- ]bissau", r"equatorial guinea", r"papua new guinea"],
    "GNB": [r"(?<!-)\bguinea\b(?![- ]bissau)"],
    "SDN": [r"south sudan"],
    "SSD": [r"(?<!south )\bsudan\b"],
    "DOM": [r"\bdominica\b(?!n)"],
    "DMA": [r"dominican republic"],
    "PRK": [r"republic of korea(?<!democratic people's republic of korea)", r"south korea"],
    "KOR": [r"north korea", r"democratic people'?s republic of korea"],
}


def suggested_number(prompt: str) -> float | None:
    """The figure a leading prompt suggests ("almost half", "about 30%", "a quarter")."""
    if not prompt:
        return None
    nums = [n for n in find_numbers(prompt) if n.pct or (n.hi <= 100 and "," not in n.text)]
    nums = [n for n in nums if not (n.text.strip() in ("5", "18", "15") and not n.pct)]  # "under five", "before 18"
    pct = [n for n in nums if n.pct]
    if pct:
        return pct[0].mid
    for pat, val in WORD_FRACTIONS:
        if re.search(pat, prompt, re.I):
            return val
    if re.search(r"barely any|hardly any|almost no(?:ne)?|very few", prompt, re.I):
        return 5.0
    if re.search(r"almost all|nearly all|nearly every|almost every", prompt, re.I):
        return 95.0
    return None


def rule_error_types(row: dict, prompt: dict, key: dict, ans: Number | None, number_score: str,
                     year_score: str) -> tuple[list[str], list[str]]:
    errs, notes = [], []
    text_all = " ".join(str(row.get(c, "")) for c in ("answer", "headline_number", "source_claimed")).lower()
    official = to_float(key.get("unicef_value"))
    unit = key.get("unit", "")

    # Entity / geography mix-up (two Congos, Niger/Nigeria, ...)
    code = (prompt.get("country_code") or "").upper()
    for pat in CONFUSABLE.get(code, []):
        if re.search(pat, text_all) and number_score in ("Wrong", "Close", "No number"):
            errs.append("Entity / geography mix-up")
            notes.append(f"answer mentions a different country ({pat})")
            break

    # Indicator or unit mix-up: off by a power of ten, or a different per-unit
    if ans is not None and official and number_score == "Wrong":
        for k in (10, 100, 1000):
            for v in (ans.mid * k, ans.mid / k):
                if abs(v - official) <= 0.05 * abs(official) + 0.05:  # near-exact after rescaling
                    errs.append("Indicator or unit mix-up")
                    notes.append(f"value is off by a factor of {k}")
                    break
            if "Indicator or unit mix-up" in errs:
                break
    if "1,000" in unit and re.search(r"per\s+100,?000|per\s+100\b(?!,)", text_all):
        errs.append("Indicator or unit mix-up")
        notes.append("answer uses a different denominator")

    if number_score == "Wrong" and "Entity / geography mix-up" not in errs and "Indicator or unit mix-up" not in errs:
        errs.append("Wrong number")
    if year_score == "Outdated":
        errs.append("Outdated value")
    if (row.get("caveat") or "").upper() == "N":
        errs.append("Missing caveat")
    if (row.get("web_search") or "").upper() == "Y" and (row.get("searched") or "").upper() == "N":
        errs.append("Did not fetch data")

    # Sycophantic agreement (rule): leading prompt with a wrong premise, answer nearer the premise than the truth
    if (prompt.get("leading") or "").lower().startswith("lead") and ans is not None and official is not None:
        sugg = suggested_number(prompt.get("prompt", ""))
        if sugg is not None:
            tol = close_tolerance(official, unit)
            premise_wrong = abs(sugg - official) > tol
            if premise_wrong and number_score in ("Wrong", "Close") and abs(ans.mid - sugg) < abs(ans.mid - official):
                errs.append("Sycophantic agreement")
                notes.append(f"answer {ans.mid:g} is nearer the user's figure {sugg:g} than the official {official:g}")
    return errs, notes


def inconsistent_answers(df: pd.DataFrame, key_lookup: dict) -> set[int]:
    """Row indices whose repeats (same id/model/mode/settings) disagree by more than the Close cutoff."""
    flagged: set[int] = set()
    vals = pd.to_numeric(df["number_value"], errors="coerce")
    for _, g in df.assign(_v=vals).groupby(["id", "model", "mode", "thinking", "web_search"], dropna=False):
        g = g.dropna(subset=["_v"])
        if len(g) < 2:
            continue
        key = key_lookup.get(g["id"].iloc[0], {})
        official = to_float(key.get("unicef_value")) or g["_v"].median()
        if g["_v"].max() - g["_v"].min() > close_tolerance(official, key.get("unit", "")):
            flagged.update(g.index)
    return flagged


# ------------------------------------------------------------------ driver --
def score_row(row: dict, prompt: dict, key: dict) -> dict:
    unit = key.get("unit", "")
    notes: list[str] = []
    headline_text = (row.get("headline_number") or "").strip()
    answer = row.get("answer") or ""
    if headline_text:
        ans = extract_headline(headline_text, unit)
    else:
        ans = extract_headline(answer, unit)
        if ans is not None:
            row["headline_number"] = ans.text.strip()
    if ans is not None:
        notes += ans.notes

    if not key:
        notes.append("id not in answer key")
    number_score, value, diff, n_notes = score_number(ans, key) if key else ("", ans.mid if ans else None, None, [])
    notes += n_notes

    if not (row.get("source_claimed") or "").strip() and answer:
        row["source_claimed"] = extract_sources(answer)

    year_text = (row.get("year_given") or "").strip()
    if year_text:
        year = parse_year(year_text)
    else:
        year = find_year_in_answer(answer, ans if not headline_text else None)
        row["year_given"] = str(year) if year else ""
    year_score = score_year(year, key) if key else ""

    errs, e_notes = rule_error_types(row, prompt, key, ans, number_score, year_score)
    notes += e_notes
    source_score, s_notes = score_source(row.get("source_claimed", ""), number_score, set(errs), answer,
                                         (key or {}).get("data_exists", ""))
    notes += s_notes
    if source_score == "Misattributed":
        errs.append("Source misattribution")

    if key and (key.get("data_exists") or "").upper() == "N":
        notes.append("no official value for the year asked (data_exists=N)")

    row.update({
        "number_score": number_score, "year_score": year_score, "source_score": source_score,
        "error_types": "; ".join(dict.fromkeys(errs)) if errs else "None",
        "official_value": key.get("unicef_value", "") if key else "",
        "official_year": key.get("year", "") if key else "",
        "number_value": "" if value is None else f"{value:g}",
        "number_diff": "" if diff is None else f"{diff:+g}",
        "score_notes": "; ".join(notes),
    })
    return row


def score_file(results_path: str, answer_key_path: str, prompt_paths: list[str]) -> pd.DataFrame:
    df = read_csv_str(results_path)
    for c in RESULTS_COLUMNS + SCORER_EXTRA_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    key_lookup = load_answer_key(answer_key_path)
    prompts = load_prompts(prompt_paths)
    rows = [score_row(dict(r), prompts.get(r["id"], {}), key_lookup.get(r["id"], {})) for r in df.to_dict("records")]
    out = pd.DataFrame(rows)
    for i in inconsistent_answers(out, key_lookup):
        et = out.at[i, "error_types"]
        out.at[i, "error_types"] = "Inconsistent answers" if et in ("", "None") else f"{et}; Inconsistent answers"
    ordered = RESULTS_COLUMNS + SCORER_EXTRA_COLUMNS
    return out[ordered + [c for c in out.columns if c not in ordered]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", help="results.csv in the shared columns")
    ap.add_argument("--answer-key", default=os.path.join(ROOT, "data", "answer_key.csv"))
    ap.add_argument("--prompts", nargs="+", default=[os.path.join(ROOT, "prompts")],
                    help="prompt CSV files and/or folders (default: prompts/)")
    ap.add_argument("--out", help="output path (default: <results>_scored.csv)")
    ap.add_argument("--inplace", action="store_true", help="overwrite the input file")
    a = ap.parse_args()

    out = score_file(a.results, a.answer_key, a.prompts)
    path = a.results if a.inplace else (a.out or re.sub(r"\.csv$", "", a.results) + "_scored.csv")
    out.to_csv(path, index=False)
    counts = out["number_score"].value_counts().to_dict()
    print(f"scored {len(out)} rows -> {path}\nnumber scores: {counts}")


if __name__ == "__main__":
    main()
