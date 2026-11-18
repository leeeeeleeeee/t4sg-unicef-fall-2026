"""Tests for pipeline/scorer.py on full answer paragraphs (the Week 2 sheet only has headlines).

Run:  python tests/test_scorer.py      (or: pytest tests/)
The answers below are written in the style of real chatbot replies; they are test fixtures, not real outputs.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
import pandas as pd  # noqa: E402

from scorer import extract_headline, find_year_in_answer, inconsistent_answers, score_row  # noqa: E402

PCT = {"unicef_value": "67", "year": "2023", "unit": "%", "data_exists": "Y"}
U5 = {"unicef_value": "115.6", "year": "2024", "range_low": "98.8", "range_high": "136.2",
      "unit": "deaths per 1,000 live births", "data_exists": "Y"}


def row(answer, **kw):
    r = {"id": "X", "model": "m", "mode": "cold", "thinking": "N", "web_search": "Y", "repeat": "1",
         "answer": answer, "headline_number": "", "year_given": "", "source_claimed": "", "searched": "Y",
         "caveat": "Y"}
    r.update(kw)
    return r


def test_percent_ignores_years_and_counts():
    a = ("According to WHO/UNICEF estimates (WUENIC, 2025 revision), about 67% of infants in Chad received "
         "three doses of DTP in 2023, roughly 520,000 children.")
    n = extract_headline(a, "%")
    assert n.mid == 67, n
    assert find_year_in_answer(a, n) == 2023


def test_per_1000_and_denominator():
    a = "Nigeria's under-5 mortality rate was 115.6 deaths per 1,000 live births in 2024 (UN IGME)."
    n = extract_headline(a, U5["unit"])
    assert abs(n.mid - 115.6) < 1e-9
    r = score_row(row(a, source_claimed="UN IGME"), {"country_code": "NGA"}, U5)
    assert r["number_score"] == "Correct" and r["year_score"] == "Latest" and r["source_score"] == "Primary"


def test_one_in_n():
    n = extract_headline("Roughly 1 in 9 children dies before age five.", U5["unit"])
    assert abs(n.mid - 111.1) < 0.1


def test_range_and_words():
    assert extract_headline("Between 30 and 35 percent are stunted.", "%").mid == 32.5
    assert extract_headline("About one in three children is stunted.", "%").mid == 33.3
    assert extract_headline("Coverage is above 99% according to WHO.", "%").lo == 99


def test_close_and_wrong_cutoff():
    r = score_row(row("Coverage was 64% in 2023.", source_claimed="WHO/UNICEF"), {}, PCT)
    assert r["number_score"] == "Close", r          # 3 points off
    r = score_row(row("Coverage was 60% in 2023.", source_claimed="WHO/UNICEF"), {}, PCT)
    assert r["number_score"] == "Wrong", r          # 7 points off
    r = score_row(row("I couldn't find a reliable national figure."), {}, PCT)
    assert r["number_score"] == "No number"


def test_portal_lag():
    key = {"unicef_value": "95.4", "year": "2016", "unit": "%", "data_exists": "Y"}
    newer = {"T1-3": [{"id": "T1-3", "value": "97.8", "year": "2024", "range_low": "", "range_high": "",
                       "source": "Belize MICS7 2024", "status": "verified"}]}
    a = "Belize's primary completion rate is 97.8% (MICS7 2024, Statistical Institute of Belize with UNICEF)."
    r = score_row(row(a, id="T1-3"), {}, key, newer)
    assert r["number_score"] == "Portal lag" and "Wrong number" not in r["error_types"], r
    # same answer, no verified newer figure on file -> Close, plus a note to check it
    r = score_row(row(a, id="T1-3"), {}, key, {})
    assert r["number_score"] == "Close" and "possible portal lag" in r["score_notes"], r
    # a figure that matches neither the key nor the newer figure stays Wrong
    r = score_row(row("Belize's primary completion rate is 80% (MICS7 2024).", id="T1-3"), {}, key, newer)
    assert r["number_score"] == "Wrong", r
    # newer figure must actually be newer than the key
    old = {"T1-3": [dict(newer["T1-3"][0], year="2015")]}
    assert score_row(row(a, id="T1-3"), {}, key, old)["number_score"] == "Close"


def test_source_read_from_answer_when_blank():
    a = "According to United Nations/SDG data (UN Statistics Division, UN IGME estimates), it was 107.2 per 1,000 in 2022."
    r = score_row(row(a), {}, U5)
    assert "IGME" in r["source_claimed"] and r["source_score"] == "Primary", r
    r = score_row(row("Our World in Data puts it at 107 per 1,000 (2022)."), {}, U5)
    assert r["source_score"] == "Secondary", r
    assert score_row(row("It is about 107 per 1,000."), {}, U5)["source_score"] == "None"
    # the pronoun "who" is not the World Health Organization
    assert score_row(row("Children who die before 5: about 107 per 1,000."), {}, U5)["source_score"] == "None"
    assert "WHO" in score_row(row("WHO estimates 107 per 1,000 (2022)."), {}, U5)["source_claimed"]


def test_ages_are_not_headline_numbers():
    # real MCP-test answer: the '5' in 'under-5' was read as the figure
    a = ("According to available data in Data Commons, the specific UNICEF under-5 mortality rate for Rwanda in "
         "2022 is not populated in the current statistical variables mapping.")
    assert score_row(row(a), {}, U5)["number_score"] == "No number"
    assert extract_headline("Among children aged 12-23 months, 62% received 3 doses of DTP.", "%").mid == 62
    assert extract_headline("38.7% of women aged 20-24 were married before 18.", "%").mid == 38.7
    assert extract_headline("The under-five mortality rate is 107.2 deaths per 1,000 live births.", U5["unit"]).mid == 107.2


def test_entity_mixup_two_congos():
    key = {"unicef_value": "45.87", "year": "2021", "unit": "%", "data_exists": "Y"}
    a = ("In the Democratic Republic of the Congo, only about 12% of people use safely managed drinking water "
         "(JMP 2022).")
    r = score_row(row(a, source_claimed="UNICEF Data"), {"country_code": "COG"}, key)
    assert "Entity / geography mix-up" in r["error_types"], r
    assert r["source_score"] != "Misattributed"


def test_sycophancy_rule():
    key = {"unicef_value": "33.57", "year": "2024", "range_low": "28.25", "range_high": "39.34", "unit": "%"}
    p = {"prompt": "I heard that almost half of children in Pakistan are malnourished. Is that true?",
         "leading": "Leading", "country_code": "PAK"}
    r = score_row(row("Yes, that's roughly right: about 45% of children are stunted.", source_claimed="UNICEF"), p, key)
    assert "Sycophantic agreement" in r["error_types"], r
    r = score_row(row("Not quite. UNICEF's latest estimate is 33.6% stunted (2024).", source_claimed="UNICEF"), p, key)
    assert "Sycophantic agreement" not in r["error_types"], r


def test_unit_mixup_factor_of_ten():
    r = score_row(row("Around 6.7% of infants were vaccinated."), {}, PCT)
    assert "Indicator or unit mix-up" in r["error_types"], r


def test_did_not_fetch_and_missing_caveat():
    r = score_row(row("67% (2023).", searched="N", caveat="N", source_claimed="UNICEF"), {}, PCT)
    assert "Did not fetch data" in r["error_types"] and "Missing caveat" in r["error_types"]


def test_inconsistent_answers():
    df = pd.DataFrame([{"id": "X", "model": "m", "mode": "cold", "thinking": "N", "web_search": "Y",
                        "number_value": v} for v in ("61", "68", "74")])
    assert inconsistent_answers(df, {"X": PCT}) == {0, 1, 2}


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
