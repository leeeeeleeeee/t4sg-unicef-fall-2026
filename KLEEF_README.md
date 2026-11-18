# Scorer, AI judge and MCP test

My part of the benchmark tool: scoring the answers, the AI judge, and the MCP comparison. Everything reads and
writes the shared columns, so it plugs into Lily's runner and Bianca's report as is.

## What's here

| Piece | Status | Files |
|---|---|---|
| Week 2 test set in the shared columns | Done | `data/test_set/`, made by `pipeline/export_week2.py` |
| Scorer | Done. Matches our Week 2 hand Number scores on 71/87 rows, plus 2 rows now scored Portal lag; every disagreement explained | `pipeline/scorer.py`, `reports/scorer_validation.md` |
| Close cutoff | 3 percentage points / 10% for rates | `docs/scoring_rules.md` |
| Portal lag score (requested by UNICEF) | Done | `data/newer_unicef_figures.csv`, `docs/scoring_rules.md` |
| AI judge | Run on 30 rows (labels still being finalised) | `pipeline/judge.py`, `config/judge_rubric.md`, `reports/judge_agreement.md` |
| MCP test | Run on 10 prompts | `pipeline/mcp_test.py`, `reports/mcp_test_summary.md`, `results/mcp_test/` |
| Extra edge-case prompts | 18 prompts, each checked against UNICEF's API | `prompts/kleef_prompts.csv`, `data/test_set/kleef_prompts_notes.csv` |

## Results so far

### The Week 2 answer key had errors

Re-checking every key row against UNICEF's SDMX API (16 Nov) turned up two prompts where the chatbots were
right and we'd marked them wrong:

- **P2 (Chad DTP3 2023):** the 2023 value is 67%. The key had 71%, which is the 2025 value. All three chatbots said 67%.
- **R5 (Ethiopia underweight):** the question asks about underweight (21.2%), but the key used wasting (6.8%).
  All three chatbots said about 21%.

There were also smaller fixes: wrong years (R1, R2), a wrong indicator code (T2-2 should be primary
completion, 53.9% from 2015), missing uncertainty ranges (N1, T1-1), and P5 "latest" moved to the 2024 JME
estimate. With the corrected key, Correct answers go from 45 to 56 of 87. Every change and its API query is
in `data/test_set/answer_key_corrections.csv`.

### Portal lag

UNICEF's data portal can lag behind UNICEF's own reports, and our key comes from the portal. Answers that
match a newer UNICEF figure now get their own score, **Portal lag**, instead of Wrong. Newer figures live in
`data/newer_unicef_figures.csv` with their source. So far that's Belize primary completion: MICS7 2024 = 97.8%,
while the portal has 95.4% from 2015-16. Two Week 2 answers (Claude and ChatGPT on T1-3) now score Portal lag.
Answers that cite a newer year but match nothing on the list get a "possible portal lag" note to check by hand.

### MCP test (Gemini 3.5 Flash-Lite, 10 prompts)

| | without MCP | with Data Commons MCP |
|---|---|---|
| Correct | 4/10 | 8/10 |
| Primary source | 5/10 | 9/10 |
| Credited UNICEF with a wrong number | 4/10 | 1/10 |
| Fell for the leading question (N5, T2-3) | 2/2 | 0/2 |
| Called a tool / used its number | n/a | 10/10 / 10/10 |
| Avg seconds per answer | 1.1 | 11.7 |

With the tools, the model grounds its answers and stops agreeing with leading questions. But Data Commons'
newest values are often from 2022 and from an older estimate round (Nigeria under-5 mortality 107.2 vs
UNICEF's 115.6; Chad DTP3 60% vs 67%), so grounded answers can still be behind UNICEF. Costs shown are at
list price; the free tier cost nothing.

### AI judge (Nemotron Ultra, free)

| Label | Agreement with our labels | Kappa |
|---|---|---|
| Sycophantic agreement | 77% | 0.61 |
| Narrative distortion | 73% | 0.37 |
| Pattern answer | 87% | n/a (no examples in our labels) |

On sycophancy it misses the subtle cases, where the answer gives the right number and then piles on figures
that support the user. On narrative distortion it over-flags, mostly by calling source or country errors
"distortion". Next: finalise the 30 labels, then tighten the rubric on those two points. The Week 2 sheet only
has summaries of each answer, not full text, so agreement should improve on real runs.

## How to run

```bash
pip install -r requirements-kleef.txt
```

Score a run (after the runner writes `results/<run>/results.csv`):

```bash
python pipeline/scorer.py results/midpoint/results.csv --answer-key data/answer_key.csv --prompts prompts/
```

Check the scorer against our Week 2 hand scores, and run the tests:

```bash
python pipeline/validate_scorer.py
```

```bash
python tests/test_scorer.py
```

AI judge (needs `OPENROUTER_API_KEY` in `.env`; `--dry-run` shows the prompts without calling anything):

```bash
python pipeline/judge.py --validate
```

```bash
python pipeline/judge.py results/midpoint/results_scored.csv --answer-key data/answer_key.csv
```

MCP test (needs `DC_API_KEY` from https://apikeys.datacommons.org and `GEMINI_API_KEY`; try `--limit 5` first):

```bash
python pipeline/mcp_test.py
```

Rebuild the test set from the Week 2 sheets (downloaded as .xlsx):

```bash
python pipeline/export_week2.py --answer-key "Week 2_ Answer Key.xlsx" --results "Week 2_ Benchmark Results.xlsx"
```

Models: the judge defaults to `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`, deliberately not a Google
model, since Gemini is one of the chatbots being judged. The MCP test defaults to `gemini/gemini-3.5-flash-lite`,
which is free and supports tool calling. `gemini-2.5-flash` is retired for new keys. Override with
`JUDGE_MODEL` / `MCP_TEST_MODEL` in `.env`.

## For the team

- **Lily:** the scorer fills `headline_number`, `year_given`, `source_claimed` and the score columns when
  they're blank, and adds `official_value, official_year, number_value, number_diff, score_notes` after the
  shared columns. Output goes to `<results>_scored.csv` (`--inplace` to overwrite). The midpoint run scores
  will fill in once `data/answer_key.csv` exists.
- **Bianca:** `reports/week2_rescored_with_corrected_key.csv` is Week 2 re-scored in the shared columns.
  `number_score` can now also be `Portal lag`; I gave it a colour in `report.py` (blue) so the charts don't
  break. It isn't counted in "% Correct" yet. Your call whether it should be. Missing caveat comes from
  the `caveat` column, so the caveat check should write Y/N there.
- **Shravya:** the judge and MCP test call LiteLLM directly; switching to `ask()` is a few lines in
  `judge.call_judge` and `mcp_test.ask`. The MCP test needs a model with tool calling.
- **Anya:** the key corrections above are good checks for `answer_key.py`. My prompts K07, K08, K09 and K17
  have no data for the year/place asked and should come out `data_exists = N`.

## Known limits

- Week 2 only saved screenshots, so the scorer was validated on the headline, year and source we wrote down.
  Number extraction from full answers is covered by `tests/test_scorer.py` and the MCP run, but the first
  real runner output is worth spot-checking.
- Use `datacommons-mcp==1.2.1` (pinned). 1.3 and later call a Data Commons "agent" API that returns 404 for our
  keys. 1.2.1 has the two tools from our Week 1 notes (`search_indicators`, `get_observations`).
