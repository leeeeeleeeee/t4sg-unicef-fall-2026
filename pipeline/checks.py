"""Automatic caveat check and source (link) check used by report.py.

Caveat check: does an answer carry the notes that come with UNICEF's official numbers?
    estimate or range  - says the figure is an estimate, or gives a range / uncertainty
    year               - names the year the figure refers to
    source             - names where the figure comes from (UNICEF, UN IGME, DHS, a link, ...)
    definition         - says what is being measured (per 1,000 live births, percentage of children aged ...)

Source check: do the links the model cited actually exist?

Usage:
    python pipeline/checks.py caveat "Nigeria's under-5 mortality was an estimated 115.6 per 1,000 live births in 2024 (UN IGME)."
    python pipeline/checks.py links results/<run>/results.csv     # writes results/<run>/link_check.csv (needs internet)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

CAVEAT_ELEMENTS = ["caveat_estimate", "caveat_year", "caveat_source", "caveat_definition"]

_PATTERNS = {
    "caveat_estimate": re.compile(
        r"\bestimat|\bapprox|\baround\b|\babout\b|\broughly\b|\brange\b|\buncertain|"
        r"confidence interval|margin of error|±|\+/-|"
        r"\d[\d.,]*\s*%?\s*(?:-|–|—|to)\s*\d[\d.,]*", re.I),
    "caveat_year": re.compile(r"\b(?:19|20)\d{2}\b"),
    "caveat_source": re.compile(
        r"\bunicef\b|\bwho\b|world bank|\bigme\b|\bdhs\b|\bmics\b|\bsurvey\b|data warehouse|"
        r"data commons|\bsource\b|according to|\breport(?:ed)?\b|https?://", re.I),
    "caveat_definition": re.compile(
        r"defin|refers to|\bmeasur|per\s*1[,.]?000|live births|percentage of|proportion of|"
        r"share of|\baged?\s+\d|under[- ](?:5|five)\b|months? old|\bindicator\b", re.I),
}

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def caveat_text(row) -> str:
    """Text to check: the model's answer if we have it, otherwise the tester's caveat note (column P)."""
    answer = str(row.get("answer", "") or "").strip()
    return answer if answer else str(row.get("caveat", "") or "").strip()


def caveat_check(text: str) -> dict:
    """Return 0/1 for each caveat element plus caveat_score (how many of the 4 were found)."""
    text = text or ""
    found = {name: float(bool(p.search(text))) for name, p in _PATTERNS.items()}
    found["caveat_score"] = sum(found.values())
    return found


# ------------------------------------------------------------------ link check

def _status(session, url: str) -> tuple[str, str]:
    import requests
    try:
        r = session.head(url, allow_redirects=True, timeout=10)
        if r.status_code in (405, 501) or r.status_code >= 400:
            r = session.get(url, allow_redirects=True, timeout=15, stream=True)
        code = r.status_code
    except requests.exceptions.ConnectionError as exc:
        msg = str(exc).lower()
        if "name or service not known" in msg or "nodename nor servname" in msg \
                or "getaddrinfo failed" in msg or "name resolution" in msg:
            return "no_such_site", ""
        return "error", ""
    except requests.RequestException:
        return "error", ""
    if code < 400:
        return "ok", str(code)
    if code in (401, 403, 429):
        return "blocked", str(code)
    return "broken", str(code)


def check_links_in_results(results_path) -> pd.DataFrame:
    """Test every link cited in the answer or source columns; write link_check.csv next to the results."""
    import requests
    path = Path(results_path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    rows, cache = [], {}
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0 (t4sg-unicef link check)"
        for _, r in df.iterrows():
            text = f"{r.get('answer', '')} {r.get('source_claimed', '')}"
            for url in dict.fromkeys(u.rstrip(".,;:") for u in URL_RE.findall(text)):
                if url not in cache:
                    cache[url] = _status(session, url)
                status, code = cache[url]
                rows.append({"id": r.get("id", ""), "model": r.get("model", ""), "url": url,
                             "status": status, "http_code": code})
    out = pd.DataFrame(rows, columns=["id", "model", "url", "status", "http_code"])
    out.to_csv(path.parent / "link_check.csv", index=False)
    print(f"Checked {len(cache)} unique links ({len(out)} citations); wrote {path.parent / 'link_check.csv'}")
    return out


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "caveat":
        print(caveat_check(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "links":
        check_links_in_results(sys.argv[2])
    else:
        print(__doc__)
