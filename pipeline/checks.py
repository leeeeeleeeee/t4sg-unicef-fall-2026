"""Automatic checks on model answers.

1. Caveat check: does the answer carry the four things a good UNICEF answer should?
     estimate_or_range  - says the number is an estimate / gives a range / says it's modelled
     year               - says which year the data is for (or that it's out of date)
     source             - names where the number comes from (UNICEF, DHS, MICS, a link...)
     definition         - says what the indicator measures (per 1,000 live births, under 5...)
   It is keyword-based on purpose, so anyone can read and tune the patterns below.

2. Source check: do the links and websites the answer cites actually exist?

Usage:
    python pipeline/checks.py caveats data/week2/week2_results_raw.tsv   # test on column P
    python pipeline/checks.py links results/week2/results.csv           # needs internet
"""

import re
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

CAVEAT_PATTERNS = {
    "estimate_or_range": [
        r"\bestimat", r"\bapprox", r"\broughly\b", r"~\s*\d", r"\bmodel(l)?ed\b",
        r"model-based", r"statistical model", r"\buncertain", r"confidence (interval|grade)",
        r"\brange\b", r"\bbetween \d", r"\d\s*(–|-|to)\s*\d+\s*%", r"\bhover", r"\bprojection",
        r"margin of error", r"\brounded\b", r"\bnot (a )?direct count", r"\bcalculat",
        r"\binferen", r"\bmethod", r"\bnot verified\b", r"\bunverified\b", r"\bsurvey vs",
    ],
    "year": [
        r"\b(19|20)\d{2}\b", r"\byear\b", r"\bdata vintage\b", r"\bout of date\b",
        r"\boutdated\b", r"\bolder (data|figures)\b", r"\blatest\b", r"\bmost recent\b",
        r"\bsince \d{4}\b", r"\bpredate",
    ],
    "source": [
        r"\bUNICEF\b", r"\bWHO\b", r"\bIGME\b", r"\bDHS\b", r"\bMICS\d?\b", r"\bJME\b",
        r"\bJMP\b", r"\bWUENIC\b", r"\bWorld Bank\b", r"\bUNESCO\b", r"\bUIS\b",
        r"\bdata ?warehouse\b", r"\bdatabase\b", r"\bdata portal\b", r"\bfact ?sheet\b",
        r"https?://", r"\b[\w-]+\.(org|gov|int|com|net)\b", r"\bsources?\b",
        r"\bsecondary\b", r"\bsurvey\b",
    ],
    "definition": [
        r"\bdefin", r"\brefers to\b", r"\bmeasures?\b", r"\bmeans\b", r"\bindicator\b",
        r"per 1,?000 live births", r"\b(percentage|share|proportion) of\b", r"\baged? \d",
        r"\bunder(-| )?(5|five)\b", r"height-for-age", r"weight-for-(height|age)",
        r"\bcompletion rate\b", r"\bnot the same as\b", r"\bdifferent (measure|indicator|thing)\b",
        r"\bsomething different\b", r"\bdoes(n't| not) mean\b", r"\benrol(l)?ment", r"\bintake\b", r"\bformula\b",
        r"\bnot (just )?formal\b", r"\bfacilities, not\b", r"\bvs\.? (household|facility)",
    ],
}
CAVEAT_ELEMENTS = list(CAVEAT_PATTERNS)
_COMPILED = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in CAVEAT_PATTERNS.items()}


def caveat_check(text):
    """Return {element: True/False for each of the 4 elements, 'caveat_score': 0-4}."""
    text = "" if text is None or (isinstance(text, float) and pd.isna(text)) else str(text)
    found = {k: any(p.search(text) for p in pats) for k, pats in _COMPILED.items()}
    found["caveat_score"] = sum(found.values())
    return found


def caveat_text(row):
    """Text to check: the model's answer if we have it, otherwise the tester's caveat note."""
    answer = str(row.get("answer", "") or "")
    if answer.strip() and answer.lower() != "nan":
        return answer
    note = str(row.get("caveat", "") or "")
    # The tester's note: "No, no year, no survey named" describes a MISSING caveat.
    return "" if human_caveat_label(note) == "no" else note


def human_caveat_label(note):
    """Column P -> 'yes', 'no', 'yes_no_detail' (just 'Yes') or 'unknown'."""
    n = str(note or "").strip()
    low = n.lower()
    if not n or low == "nan" or "(fill" in low:
        return "unknown"
    if low.startswith("no") or low.startswith("only after"):
        return "no"
    if re.fullmatch(r"y(es)?\.?", low):
        return "yes_no_detail"
    return "yes"


def test_on_column_p(path):
    """Run the caveat check on column P and compare with the tester's Yes/No."""
    sep = "\t" if str(path).endswith(".tsv") else ","
    sheet = pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False)
    col = next(c for c in sheet.columns if c.startswith("Caveat included?"))
    rows = []
    for _, r in sheet.iterrows():
        note = r[col]
        res = caveat_check(note)
        rows.append({"id": r["ID"], "chatbot": r["Chatbot"], "human": human_caveat_label(note),
                     **res, "note": note})
    df = pd.DataFrame(rows)
    testable = df[df["human"].isin(["yes", "no"])]
    # A "Yes" note should mention at least one element; a "No" note may still describe one
    # (e.g. "No, ... did mention the certificate split"), so we score agreement on "Yes" rows
    # and report element counts for "No" rows separately.
    yes = testable[testable["human"] == "yes"]
    hit = (yes["caveat_score"] > 0).mean() if len(yes) else float("nan")
    print(f"Column P rows: {len(df)} | detailed Yes: {len(yes)} | No: {(testable.human=='no').sum()}"
          f" | bare 'Yes' (nothing to check): {(df.human=='yes_no_detail').sum()}"
          f" | blank/FILL: {(df.human=='unknown').sum()}")
    print(f"Detailed 'Yes' notes where the check found >=1 element: {hit:.0%}")
    print("Elements found in detailed 'Yes' notes:")
    for k in CAVEAT_ELEMENTS:
        print(f"  {k:18s} {yes[k].mean():.0%}")
    misses = yes[yes["caveat_score"] == 0]
    if len(misses):
        print("\n'Yes' notes the check could not place (tune patterns or check the note):")
        for _, r in misses.iterrows():
            print(f"  {r['id']:6s} {r['chatbot']:8s} {r['note'][:110]}")
    return df


# ---------------------------------------------------------------- source / link check

URL_RE = re.compile(r"https?://[^\s)\]>\"'，]+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:org|gov|int|com|net|edu|et|uk|io|info))\b", re.I)
SKIP_DOMAINS = {"drive.google.com", "docs.google.com"}  # our own screenshot links


def extract_links(text):
    """Full URLs plus bare domains like 'statisticsoftheworld.com'."""
    text = "" if text is None else str(text)
    urls = [u.rstrip(".,;:") for u in URL_RE.findall(text)]
    in_urls = {urlparse(u).netloc.lower() for u in urls}
    leftover = URL_RE.sub(" ", text)
    domains = {d.lower() for d in DOMAIN_RE.findall(leftover)} - in_urls
    links = urls + [f"https://{d}" for d in sorted(domains)]
    return [l for l in links if urlparse(l).netloc.lower() not in SKIP_DOMAINS]


def check_link(url, session=None, timeout=10):
    """Classify one link: ok / broken / no_such_site / blocked / error."""
    import requests
    session = session or requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (t4sg-unicef link check)"}
    try:
        resp = session.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        if resp.status_code in (405, 403, 400) or resp.status_code >= 500:
            resp = session.get(url, allow_redirects=True, timeout=timeout, headers=headers,
                               stream=True)
        code = resp.status_code
    except requests.RequestException as err:
        # A made-up website fails at the "look up the name" step.
        host = urlparse(url).hostname or ""
        try:
            socket.getaddrinfo(host, 443)
        except socket.gaierror:
            return {"url": url, "status": "no_such_site", "http_code": ""}
        return {"url": url, "status": "error", "http_code": type(err).__name__}
    if code < 400:
        status = "ok"
    elif code in (404, 410):
        status = "broken"
    else:  # 401/403/429/5xx: the site exists but won't let a script in
        status = "blocked"
    return {"url": url, "status": status, "http_code": code}


def check_links_in_results(results_path, out_path=None):
    """Check every link cited in a results file; saves link_check.csv next to it."""
    import requests
    results_path = Path(results_path)
    out_path = Path(out_path) if out_path else results_path.parent / "link_check.csv"
    df = pd.read_csv(results_path, dtype=str, keep_default_na=False)
    cited = []
    for i, r in df.iterrows():
        text = " ".join(str(r.get(c, "")) for c in ["answer", "source_claimed"])
        for link in extract_links(text):
            cited.append({"row": i, "id": r["id"], "model": r["model"], "url": link})
    cited = pd.DataFrame(cited, columns=["row", "id", "model", "url"])

    cache = {}
    if out_path.exists():  # reuse earlier answers so re-runs are quick
        old = pd.read_csv(out_path, dtype=str, keep_default_na=False)
        cache = {r["url"]: {"status": r["status"], "http_code": r["http_code"]}
                 for _, r in old.iterrows()}
    session = requests.Session()
    unique = [u for u in cited["url"].unique() if u not in cache]
    print(f"{len(cited)} cited links, {cited['url'].nunique()} unique, {len(unique)} to check")
    for n, url in enumerate(unique, 1):
        res = check_link(url, session)
        cache[url] = {"status": res["status"], "http_code": res["http_code"]}
        print(f"  [{n}/{len(unique)}] {res['status']:12s} {url}")
        time.sleep(0.2)
    cited["status"] = cited["url"].map(lambda u: cache[u]["status"])
    cited["http_code"] = cited["url"].map(lambda u: cache[u]["http_code"])
    cited.to_csv(out_path, index=False, lineterminator="\n")
    print(f"Saved {out_path}")
    print(cited["status"].value_counts().to_string())
    return cited


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("caveats", "links"):
        sys.exit(__doc__)
    if sys.argv[1] == "caveats":
        test_on_column_p(sys.argv[2])
    else:
        check_links_in_results(sys.argv[2])


if __name__ == "__main__":
    main()
