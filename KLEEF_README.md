# Kleef: scorer, AI judge and MCP test (evaluation lead)

Everything here uses the shared columns from the brief, so it drops into the repo as is. Folder layout
matches Lily's (`pipeline/`, `prompts/`, `data/`, `results/`, `config/`) plus `docs/`, `reports/` and `tests/`.

## Status

| Task | Status | Where |
|---|---|---|
| Export Week 2 Results + Answer Key into the shared columns | **Done** | `data/test_set/` (made by `pipeline/export_week2.py`) |
| Post the "Close" cutoff | **Ready to post** (text at the top of the doc) | `docs/scoring_rules.md` |
| `scorer.py` | **Done.** Matches hand scores on **73/87** rows (target 20); all 103 disagreements explained | `pipeline/scorer.py`, `reports/scorer_validation.md` |
| AI judge (rubric + free model + agreement on 30 rows) | **Built and tested with a fake model.** Needs a Gemini/OpenRouter key for the real run, and you should confirm the 30 labels | `config/judge_rubric.md`, `pipeline/judge.py`, `data/test_set/judge_labels.csv` |
| `prompts/kleef_prompts.csv` (optional) | **Done.** 18 edge-case prompts, all checked against UNICEF's API | `prompts/kleef_prompts.csv`, `data/test_set/kleef_prompts_notes.csv` |
| `mcp_test.py` (10 prompts, with vs without MCP) | **Built.** MCP server and tool loop tested; needs `DC_API_KEY` + a Gemini key for the real run | `pipeline/mcp_test.py`, `tests/test_mcp_loop.py` |

## Big finding: the Week 2 answer key had errors

I checked every answer-key row against UNICEF's SDMX API (16 Nov 2026):

* **P2 (Chad DTP3 2023):** the official value is **67%**. The key had 71%, which is the 2025 value. All three
  chatbots said 67% and we marked them **Wrong**.
* **R5 (Ethiopia underweight):** the prompt asks about *underweight* (**21.2%**), but the key used *wasting* (6.8%).
  All three chatbots said ~21% and we marked them **Wrong**.
* Smaller fixes: wrong years (R1, R2), wrong indicator code (T2-2 should be primary completion `ED_CR_L1`,
  value 53.9% from 2015), missing uncertainty ranges (N1, T1-1), and P5 "latest" switched to the 2024 JME estimate.
* With the corrected key, Correct answers go from 45 to **56 of 87** (ChatGPT 20, Claude 20, Gemini 16).

Every change, with its API query, is in `data/test_set/answer_key_corrections.csv`. **Tell Anya**: it shows
why an automated answer key matters, and these rows are good checks for `answer_key.py`.

## How to run

```bash
pip install -r requirements-kleef.txt
```

```bash
python pipeline/export_week2.py --answer-key "Week 2_ Answer Key.xlsx" --results "Week 2_ Benchmark Results.xlsx"
```

```bash
python pipeline/validate_scorer.py
```

```bash
python tests/test_scorer.py
```

Score any run (after Lily's runner writes `results/<run>/results.csv`):

```bash
python pipeline/scorer.py results/midpoint/results.csv --answer-key data/answer_key.csv --prompts prompts/
```

AI judge (needs `OPENROUTER_API_KEY` in `.env`; `--dry-run` and `--mock` need no key):

```bash
python pipeline/judge.py --validate --dry-run --limit 2
```

```bash
python pipeline/judge.py --validate
```

```bash
python pipeline/judge.py results/midpoint/results_scored.csv --answer-key data/answer_key.csv
```

MCP test (needs `DC_API_KEY` from https://apikeys.datacommons.org and `GEMINI_API_KEY`):

```bash
python pipeline/mcp_test.py --list-tools
```

```bash
python pipeline/mcp_test.py --limit 5
```

```bash
python pipeline/mcp_test.py
```

`.env` entries these scripts read: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DC_API_KEY`, and optionally
`JUDGE_MODEL` / `MCP_TEST_MODEL` (any LiteLLM model name). Defaults, checked 17 Nov 2026:
* judge: `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`. It isn't a Google model, since Gemini is one of the chatbots being judged.
* MCP test: `gemini/gemini-3.5-flash-lite`. It's free and supports tool calling. (`gemini-2.5-flash` is retired for new keys, and
  OpenRouter has no free Qwen or Mistral with tool calling right now.)

Match these to whatever Shravya puts in `config/connectors.yaml`.

## What you need to do

1. **Confirm the 30 judge labels** in `data/test_set/judge_labels.csv` (~10 minutes). I drafted them from the
   testers' notes; each row quotes its evidence and has a confidence level. Put your initials in
   `confirmed_by`. The brief says "30 of our hand-labeled rows", so they should be a person's call.
2. **Add the keys** to `.env` (`GEMINI_API_KEY`, `DC_API_KEY`), then run `judge.py --validate` and
   `mcp_test.py --limit 5`, then the full `mcp_test.py`. Both write their results to `reports/`.
3. **Post the Close cutoff** from `docs/scoring_rules.md`, and decide the 2 open questions at the bottom.
4. Delete the `.venv/` folder before copying this into the repo (it's only the local Python environment).

## Notes for teammates

* **Lily (runner):** the scorer reads `answer` and fills `headline_number`, `year_given` and the score columns
  if they're blank. It appends `official_value, official_year, number_value, number_diff, score_notes` after the
  shared columns. It writes `<results>_scored.csv` by default (`--inplace` to overwrite).
* **Bianca (report):** `reports/week2_rescored_with_corrected_key.csv` is the Week 2 data re-scored in the
  shared columns, ready for `report.py`. The scorer fills `Missing caveat` from the `caveat` column, so your
  caveat check should write Y/N there.
* **Shravya (connectors):** the judge and the MCP test call LiteLLM directly. Swapping in `ask()` later is a
  few lines in `judge.call_judge` and `mcp_test.ask`. The MCP test needs a model that supports tool calling.
* **Anya (answer key):** see the corrections file above. My prompts in `prompts/kleef_prompts.csv` include
  deliberate no-data cases (K07, K08, K09, K17) that should come out `data_exists = N`.

## Limits and caveats

* Week 2 saved screenshots, not answer text, so the scorer was validated on the testers' extracted headline,
  year and source. Pulling numbers from full answers is covered by `tests/test_scorer.py` (realistic answers I
  wrote), but should be spot-checked on the first real runner output.
* For the same reason, the judge's Week 2 validation only sees a summary of each answer. Expect better
  agreement on real runs with full text.
* The judge and MCP test haven't been run against a real model yet (no API keys here). Their plumbing is tested
  with a fake model and the real MCP server.
* **Use `datacommons-mcp==1.2.1`** (pinned in `requirements-kleef.txt`). Versions 1.3+ call a Data Commons
  "agent" API that returns 404 for our keys. 1.2.1 has the two tools from our Week 1 summary
  (`search_indicators`, `get_observations`) and works. If a later server version offers "playbook" resources,
  `mcp_test.py` adds a small `read_mcp_resource` bridge tool automatically.
* **First MCP results (5 prompts, Gemini 3.5 Flash-Lite):** the model called the tools on 5/5 prompts and
  used the tool's number each time. But Data Commons' newest under-5 mortality and DTP3 values are from **2022**,
  from an older estimate round (Nigeria 107.2 vs UNICEF's 115.6; Chad DTP3 60%), so MCP answers can be
  "grounded" and still behind UNICEF. That's the `lag_flag` problem in action.
