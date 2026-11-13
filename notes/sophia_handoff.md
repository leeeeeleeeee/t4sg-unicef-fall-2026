# Sophia's benchmark deliverables

Prepared for review on the team repository's `sophia` branch, November 13, 2026. Anya's review and model runs are still pending.

## What is done

- Cloned the project repository and created the local `sophia` branch.
- Created an isolated Python environment and installed `litellm`, `pandas`, `pyyaml` and `requests`.
- Added `.env.example` and ignore rules protecting local credentials and the virtual environment. Reconcile these setup files with Shravya's shared setup. Actual keys are not included.
- Wrote 18 new questions in `prompts/new_prompts.csv`, with exactly the 13 shared columns.
- Built three separate pairs for style, three for wording, and three for detail, following Sophia's revised request. The explicit comparison map is `notes/sophia_pairs.json`.
- Verified the nine underlying observations through UNICEF's public API and saved the response and per-topic evidence in `data/sophia/`.
- Wrote the compact cheat sheet in `skills/unicef_skill.md` and the review points below.

## What still needs a person or another team component

1. Configure Gemini and OpenRouter keys locally before model runs. Authenticated calls have not been tested.
2. Have Anya review the matched-pair design, definitions and evidence. Her answer-key script is not present in the cloned repository, so a code review of that script remains pending.
3. After Anya's review, incorporate feedback and propose merging `sophia` into `main`. This branch does not indicate review approval.
4. When Lily's runner and Shravya's connectors are available, run five prompts on verified free models before a full run. This checkout contains only the initial project scaffold, so an end-to-end run is not yet possible. Do not select paid models without the project's authorization.

The assignment gives Sophia a November 12 deadline, the overall deliverable a November 13 deadline at 11:59 (AM/PM and timezone unspecified), and the midpoint presentation a November 20 date.

## Pair design

The revised set has **18 prompts in nine separate pairs**: three style pairs, three wording pairs and three detail pairs. This follows Sophia's explicit revision to use three pairs per type rather than the assignment's original five. Each underlying country/indicator/year target appears exactly twice; no prompt is shared between pairs.

IDs ending in `_A` and `_B` form a pair. User types vary across pairs: naive public, academic researcher and policy analyst each appear in one pair per category. User type, country, year, intended indicator and neutral framing stay fixed within each pair.

| Category | Pairs | What changes |
| --- | --- | --- |
| Style | S01, S02, S03 | Specific numeric question vs. a vaguer “how common/widespread” question |
| Wording | S04, S05, S06 | Everyday terms vs. technical terms for the same measure |
| Detail | S07, S08, S09 | Simple question vs. the same question with requests for interpretation, source and limitations |

All 13 shared columns remain in the CSV. Only the relevant style/wording/detail tag changes within each pair. These tags describe the question, not the assumed expertise of the person asking it.

A qualitative answer or clarification request can be reasonable for a vague question; “No number” does not automatically mean factual error. The detail contrast tests explicit requests for explanation and caveats, not word count alone. Compare results within each pair under the same model, mode, settings and repeat. This small set covers all five core topics but is not balanced by topic.

## Verified observations

All nine targets exist in the saved UNICEF API response. These are fixed-year questions, not claims about the latest available observation. Full precision, units, bounds and original source fields are preserved in `data/sophia/verification.json`.

| Pair | Country | Indicator | Year | Value | Unit |
| --- | --- | --- | --- | --- | --- |
| S01 | Bangladesh | `CME_MRY0T4` | 2023 | 30.6066 | D_PER_1000_B |
| S02 | Bhutan | `IM_DTP3` | 2023 | 99.0000 | PCNT |
| S03 | Ethiopia | `PT_CHLD_Y0T4_REG` | 2016 | 2.7000 | PCNT |
| S04 | Belize | `ED_CR_L1` | 2016 | 95.4000 | PCNT |
| S05 | Pakistan | `NT_ANT_HAZ_NE2_MOD` | 2023 | 33.7008 | PCNT |
| S06 | Bangladesh | `CME_MRY0T4` | 2022 | 30.6613 | D_PER_1000_B |
| S07 | Bhutan | `IM_DTP3` | 2022 | 98.0000 | PCNT |
| S08 | Pakistan | `NT_ANT_HAZ_NE2_MOD` | 2022 | 34.1427 | PCNT |
| S09 | Ethiopia | `IM_DTP3` | 2023 | 75.0000 | PCNT |

`PCNT` means percent; `D_PER_1000_B` means deaths per 1,000 live births. The unmodified response is in `data/sophia/unicef_api_response.csv`. This evidence supports Sophia's questions; it does not replace Anya's combined answer key. Data Commons has not been checked, so no cross-source agreement or `lag_flag` is inferred.

## Review points for Anya and the scorer owner

- **Belize T1-3:** the supplied key gives 95.1% for 2016. The current API returns 95.400002% for `BLZ.ED_CR_L1._T` in 2016. Reconcile the snapshot, population and source before using the older hand score as ground truth.
- **Year mismatches:** R1 asks for Rwanda 2022 but its key labels the observation 2024. R4 asks for Indonesia 2017 but the key supplies 2025. P2 asks for Chad 2023 but the key supplies 2025. Query the requested year and explicitly mark absence instead of substituting a newer year silently.
- **Indicator mismatches:** R2 mixes the third hepatitis B dose with vaccination within 24 hours of birth. T2-2 asks for primary completion but lists `ED_CR_L3` (upper secondary). R5 asks about underweight while the key uses wasting (`NT_ANT_WHZ_NE2`). These need a clarified target or corrected key before automated scoring.
- **Source type:** Pakistan's survey stunting series and modelled stunting series are different targets. Keep `_MOD` in the new questions' metadata and retain model-based wording in every variant.
- **Meaning over numeric proximity:** the supplied benchmark notes show completion-ratio and birth-registration-definition mix-ups. A close number alone is insufficient evidence that a response used the correct indicator.
- **Historical questions:** the shared `Latest/Outdated/None` year score needs clarification for an accurate answer to an explicitly historical prompt. Preserve the requested year and observation year separately in evaluation logic; do not penalize historical correctness simply for not being latest.
- **Units:** the scoring guide's one-percentage-point tolerance does not directly specify a tolerance for deaths per 1,000 live births. Use the returned uncertainty range where available and have Kleef settle any remaining rule.

These flags come from the supplied assignment, answer-key and results PDFs. They are review findings, not edits to the team's shared sheets or scoring policy.

## Setup and next commands

From the repository root:

```sh
source .venv/bin/activate
python notes/validate_sophia.py
git status --short
```

On a fresh clone, use Python 3.11 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-sophia.txt
```

Copy `.env.example` to `.env` only if no `.env` exists. Fill `GEMINI_API_KEY` and `OPENROUTER_API_KEY` locally. Coordinate the names with Shravya's connector. A `.env` file is not automatically loaded by Python: the eventual runner should load it, or the variables must be exported in the shell.

Official key guidance: [Google AI Studio](https://aistudio.google.com/docs/api-key) and [OpenRouter quickstart](https://openrouter.ai/docs/quickstart). Free-model availability and quotas must be checked when running; this package does not promise that any model remains free.

Keep `.env` and `.venv` local. Only the blank `.env.example` belongs in Git.

## Midpoint talking points

- We added 18 prompts across the five core topics, with three separate pairs each for specificity, terminology and requested detail.
- The two questions within each pair target the same observation. We fixed the years and saved the data response so revisions can be distinguished from model errors.
- The skill teaches retrieval, definitions and caveats without including the benchmark answers.
- Anya's answer-key pipeline supplies ground truth. We flag missing years and mismatched indicators instead of treating an available but different statistic as the answer.
- Show one A/B pair and the corresponding API evidence. Present cold-versus-skill findings only after actual runs are available.

## Sources

- Supplied `Building_our_Benchmark_Tool_Deliverable (1).pdf`, pages 1-2: shared schema, setup, Sophia's tasks, review partner and dates.
- Supplied `Week 2_ Answer Key - Untitled.pdf`, page 1: original topics, codes and review issues by ID.
- Supplied `Week 2_ Benchmark Results - Untitled.pdf`: review notes for N4, R4 and T1-3 and examples of definition mismatch.
- [UNICEF SDMX documentation](https://data.unicef.org/sdmx-api-documentation/) and the exact API request recorded in `data/sophia/verification.json`.
- [UNICEF mortality](https://data.unicef.org/topic/child-survival/under-five-mortality/), [education](https://data.unicef.org/topic/education/overview/), [birth registration](https://data.unicef.org/topic/child-protection/birth-registration/) and [nutrition](https://data.unicef.org/topic/nutrition/malnutrition/) topic resources.
