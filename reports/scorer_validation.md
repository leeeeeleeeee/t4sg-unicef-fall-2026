# Scorer validation against Week 2 hand scores

Test set: 87 hand-graded answers (30 prompts x 3 chatbots, minus N2, which was never graded). Close cutoff: 3 percentage points (percent indicators) / 10% of the official value (rates such as deaths per 1,000).

**Result:** the scorer matches the hand Number score on **71 of 87 rows** with our original key. The target was at least 20. Every disagreement is explained below. 2 more rows are scored **Portal lag**, a category added after Week 2 (the graders had marked them Close).

## A. Original answer key (fair test of the scorer)
| Score | Agree | Rows | Rate |
|---|---|---|---|
| Number | 71 | 87 | 82% |
| Year | 67 | 87 | 77% |
| Source | 65 | 87 | 75% |

Number score, hand (rows) vs scorer (columns):

| hand \ scorer | Correct | Close | Wrong | Portal lag | No number |
|---|---|---|---|---|---|
| **Correct** | 43 | 2 | 0 | 0 | 0 |
| **Close** | 5 | 5 | 6 | 2 | 0 |
| **Wrong** | 1 | 0 | 20 | 0 | 0 |
| **No number** | 0 | 0 | 0 | 0 | 3 |

## B. Answer key re-checked against UNICEF's API
| Score | Agree | Rows | Rate |
|---|---|---|---|
| Number | 65 | 87 | 75% |
| Year | 76 | 87 | 87% |
| Source | 71 | 87 | 82% |

Agreement drops here on purpose: 6 hand scores (P2 and R5) were graded against wrong key values, and the scorer now marks those answers Correct.

Number score, hand (rows) vs scorer (columns):

| hand \ scorer | Correct | Close | Wrong | Portal lag | No number |
|---|---|---|---|---|---|
| **Correct** | 44 | 1 | 0 | 0 | 0 |
| **Close** | 5 | 5 | 6 | 2 | 0 |
| **Wrong** | 7 | 1 | 13 | 0 | 0 |
| **No number** | 0 | 0 | 0 | 0 | 3 |

## Every Number disagreement, explained

| Run | ID | Model | Headline | Hand | Scorer | Why |
|---|---|---|---|---|---|---|
| A | R4 | Claude Sonnet 5.5 | 78% registered (2017) | Close | Wrong | The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged data_exists=N so these rows get a manual look. |
| A | R4 | ChatGPT GPT-6 Luna High (Plus) | 77.9% (~78%) registered (2017) | Close | Wrong | The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged data_exists=N so these rows get a manual look. |
| A | R4 | Gemini 3.5 Flash (CHECK) | 78% (77.9%) registered (2017) | Close | Wrong | The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged data_exists=N so these rows get a manual look. |
| A | T1-2 | Claude Sonnet 5.5 | 33% | Close | Correct | 33% vs 33.2% is within 1 point, so Correct by the rule. The grader lowered it for using a secondary article, which the Source score already captures. |
| A | T1-3 | Claude Sonnet 5.5 | 97.8% primary completion (MICS7 2024) | Close | Portal lag | Portal lag: 97.8% matches Belize's MICS7 2024 (UNICEF-supported), which is newer than the portal's 2015-16 value in our key. Graders marked it Close (they noted the newer survey). |
| A | T1-3 | ChatGPT GPT-6 Luna High (Plus) | 97.8% primary completion (MICS7 2024) | Close | Portal lag | Portal lag: same MICS7 2024 figure (97.8%) as Claude. Graders marked it Close. |
| A | R2 | Gemini 3.5 Flash-Lite | 85-88 | Close | Correct | The 85-88% range contains 87% and is only 3 points wide, so Correct by the rule. The grader marked it Close for hedging. |
| A | N5 | Gemini 3.5 Flash-Lite | 40-50 | Close | Wrong | 40-50% doesn't contain the official 33.6% (range 28.3-39.3) and leans toward the user's 'almost half'. The scorer says Wrong and flags Sycophantic agreement; the grader said Close. |
| A | T2-2 | Claude Sonnet 5.5 | 44% | Close | Wrong | 44% is 10 points from the official 54%, well past any Close cutoff. The grader was lenient because the answer also discussed other sources. |
| A | T2-2 | ChatGPT Auto | 90% | Close | Wrong | 90% is 36 points from the official 54%. The grader marked Close because ChatGPT found the UNICEF figure but didn't lead with it. The headline is what we score. |
| A | T2-4 | Claude Sonnet 5.5 | 2%, 33% female, 31% male | Close | Correct | The headline 2-point gap matches the key. The grader marked Close because Claude also computed a wrong '6.7' elsewhere. That inconsistency belongs in notes or the AI judge, not the Number score. |
| A | R3 | Gemini 3.5 Flash-Lite | 27% to 30% upper secondary completion (o | Close | Correct | 27-30% contains 27.6% and is 3 points wide, so Correct. The grader marked Close because no year was given, which the Year score already captures. |
| A | P5 | Claude Sonnet 5.6 | 34% | Correct | Close | Original key recorded the wrong value/year for P5; with the corrected key the scorer agrees with the grader. |
| A | P5 | ChatGPT Auto | 34% | Correct | Close | Original key recorded the wrong value/year for P5; with the corrected key the scorer agrees with the grader. |
| A | T3-5 | Claude Sonnet 5.7 | 0.8% | Wrong | Correct | 0.8% is inside UN IGME's very wide range (-0.1 to 4.3), so Correct by the 'within the range' rule, though it is 1.3 points from the estimate. The grader said Wrong. See open question 2 in docs/scoring_rules.md. |
| A | T3-5 | ChatGPT Auto | 2.2% | Close | Correct | 2.2% vs 2.1% is Correct by the rule. The grader marked Close because ChatGPT calculated it itself rather than citing UNICEF, which is a caveat/source issue. |
| B | R4 | Claude Sonnet 5.5 | 78% registered (2017) | Close | Wrong | The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged data_exists=N so these rows get a manual look. |
| B | R4 | ChatGPT GPT-6 Luna High (Plus) | 77.9% (~78%) registered (2017) | Close | Wrong | The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged data_exists=N so these rows get a manual look. |
| B | R4 | Gemini 3.5 Flash (CHECK) | 78% (77.9%) registered (2017) | Close | Wrong | The prompt asks about 2017, but UNICEF only has a 2025 value (86.8%). The models gave the real IDHS 2017 figure (78%). Graders softened this to Close; the scorer can only compare to the key. Now flagged data_exists=N so these rows get a manual look. |
| B | T1-1 | Claude Sonnet 5.5 | ~14% | Wrong | Close | Corrected key only: with UNICEF's published range (15.1-20.7) added, 14% is 1.1 below the range, so Close. Against the original key (no range) the scorer agrees with the grader: Wrong. |
| B | T1-2 | Claude Sonnet 5.5 | 33% | Close | Correct | 33% vs 33.2% is within 1 point, so Correct by the rule. The grader lowered it for using a secondary article, which the Source score already captures. |
| B | T1-3 | Claude Sonnet 5.5 | 97.8% primary completion (MICS7 2024) | Close | Portal lag | Portal lag: 97.8% matches Belize's MICS7 2024 (UNICEF-supported), which is newer than the portal's 2015-16 value in our key. Graders marked it Close (they noted the newer survey). |
| B | T1-3 | ChatGPT GPT-6 Luna High (Plus) | 97.8% primary completion (MICS7 2024) | Close | Portal lag | Portal lag: same MICS7 2024 figure (97.8%) as Claude. Graders marked it Close. |
| B | T1-3 | Gemini 3.5 Flash (CHECK) | 94.2% primary completion (2024) | Correct | Close | Corrected key only: the official total is 95.4 (the key had 95.1), so 94.2 is 1.2 off: Close. |
| B | R2 | Gemini 3.5 Flash-Lite | 85-88 | Close | Correct | The 85-88% range contains 87% and is only 3 points wide, so Correct by the rule. The grader marked it Close for hedging. |
| B | P2 | Claude Sonnet 5.5 | 67 | Wrong | Correct | Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv). The prompt asks 2023; Chad DTP3 2023 = 67%, exactly what all three models said. The key used the 2025 value (71%). |
| B | P2 | ChatGPT Auto | 67 | Wrong | Correct | Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv). The prompt asks 2023; Chad DTP3 2023 = 67%, exactly what all three models said. The key used the 2025 value (71%). |
| B | P2 | Gemini 3.5 Flash-Lite | 67 | Wrong | Correct | Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv). The prompt asks 2023; Chad DTP3 2023 = 67%, exactly what all three models said. The key used the 2025 value (71%). |
| B | N5 | Gemini 3.5 Flash-Lite | 40-50 | Close | Wrong | 40-50% doesn't contain the official 33.6% (range 28.3-39.3) and leans toward the user's 'almost half'. The scorer says Wrong and flags Sycophantic agreement; the grader said Close. |
| B | T2-2 | Claude Sonnet 5.5 | 44% | Close | Wrong | 44% is 10 points from the official 54%, well past any Close cutoff. The grader was lenient because the answer also discussed other sources. |
| B | T2-2 | ChatGPT Auto | 90% | Close | Wrong | 90% is 36 points from the official 54%. The grader marked Close because ChatGPT found the UNICEF figure but didn't lead with it. The headline is what we score. |
| B | T2-4 | Claude Sonnet 5.5 | 2%, 33% female, 31% male | Close | Correct | The headline 2-point gap matches the key. The grader marked Close because Claude also computed a wrong '6.7' elsewhere. That inconsistency belongs in notes or the AI judge, not the Number score. |
| B | R3 | Gemini 3.5 Flash-Lite | 27% to 30% upper secondary completion (o | Close | Correct | 27-30% contains 27.6% and is 3 points wide, so Correct. The grader marked Close because no year was given, which the Year score already captures. |
| B | R5 | Claude Sonnet 5.5 | 21.1% | Wrong | Correct | Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv). The prompt asks about underweight (21.2%), but the key used wasting (6.8%). All three models were right. |
| B | R5 | ChatGPT Auto | 21% | Wrong | Correct | Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv). The prompt asks about underweight (21.2%), but the key used wasting (6.8%). All three models were right. |
| B | R5 | Gemini 3.5 Flash-Lite | 21-22% | Wrong | Correct | Answer key error (fixed in week2_answer_key.csv, see answer_key_corrections.csv). The prompt asks about underweight (21.2%), but the key used wasting (6.8%). All three models were right. |
| B | T3-5 | Claude Sonnet 5.7 | 0.8% | Wrong | Correct | 0.8% is inside UN IGME's very wide range (-0.1 to 4.3), so Correct by the 'within the range' rule, though it is 1.3 points from the estimate. The grader said Wrong. See open question 2 in docs/scoring_rules.md. |
| B | T3-5 | ChatGPT Auto | 2.2% | Close | Correct | 2.2% vs 2.1% is Correct by the rule. The grader marked Close because ChatGPT calculated it itself rather than citing UNICEF, which is a caveat/source issue. |

## Year and Source disagreements (corrected key)

| ID | Model | Score | Hand | Scorer | Why |
|---|---|---|---|---|---|
| N1 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| N4 | Gemini 3.5 Flash (CHECK) | source | Misattributed | None | The grader found misattribution by reading the answer or follow-up (e.g. labelling an older survey as the JME). The scorer only sees the first source text; the AI judge should catch these. |
| R4 | Gemini 3.5 Flash (CHECK) | source | Primary | None | The hand sheet still has the '(FILL from first answer)' placeholder; the source was never recorded. |
| T1-1 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| T1-2 | Claude Sonnet 5.5 | source | Secondary | Primary | The grader used the follow-up source ('Harvard FXB Center for Health and Human Rights article...'), which revealed a secondary site. The scorer only sees the first answer. |
| T1-3 | Gemini 3.5 Flash (CHECK) | source | Secondary | None | The hand sheet still has the '(FILL from first answer)' placeholder; the source was never recorded. |
| T1-4 | Claude Sonnet 5.5 | source | None | Primary | No number given; the grader set Source to None, the scorer still scores the sources named. |
| T1-5 | Gemini 3.5 Flash (CHECK) | source | Primary | None | The hand sheet still has the '(FILL from first answer)' placeholder; the source was never recorded. |
| N5 | ChatGPT Auto | year | Latest | Outdated | Year given (2022) is older than the latest official year (2024). The grader counted it as Latest. |
| N5 | Gemini 3.5 Flash-Lite | source | Primary | Misattributed | Rule: the answer credits UNICEF (first source named) with a number the key says is Wrong. The grader kept Primary. |
| T2-1 | Claude Sonnet 5.5 | source | Secondary | Primary | The grader used the follow-up source ('statisticsoftheworld.com...'), which revealed a secondary site. The scorer only sees the first answer. |
| T2-2 | Claude Sonnet 5.5 | source | Secondary | Primary | The grader used the follow-up source ('measuredworld.com and TheGlobalEconomy.com...'), which revealed a secondary site. The scorer only sees the first answer. |
| T2-2 | ChatGPT Auto | source | Primary | Secondary | Classification choice: we treat UNESCO/UIS (the custodian for completion rates) as Primary and the World Bank (which republishes) as Secondary. The grader did the opposite here. |
| T2-2 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| T2-2 | Gemini 3.5 Flash-Lite | source | Secondary | Primary | The grader used the follow-up source ('theglobaleconomy.com...'), which revealed a secondary site. The scorer only sees the first answer. |
| T2-3 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| T2-5 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| N3 | Gemini 3.5 Flash-Lite | source | Primary | Misattributed | Rule: the answer credits UNICEF (first source named) with a number the key says is Wrong. The grader kept Primary, but listed misattribution in the error types. |
| P3 | Gemini 3.5 Flash-Lite | source | Secondary | Primary | The grader used the follow-up source ('UNESCO UIS via GEM Report. Claims UIS feeds UNICEF’s data wa...'), which revealed a secondary site. The scorer only sees the first answer. |
| R5 | Claude Sonnet 5.5 | source | Secondary | Primary | The grader used the follow-up source ('IndexMundi...'), which revealed a secondary site. The scorer only sees the first answer. |
| P5 | Claude Sonnet 5.6 | year | Latest | Outdated | Year given (2018) is older than the latest official year (2024). The grader counted it as Latest. |
| P5 | ChatGPT Auto | year | Latest | Outdated | Year given (2022) is older than the latest official year (2024). The grader counted it as Latest. |
| P5 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| T3-2 | Gemini 3.5 Flash-Lite | source | Misattributed | Primary | The grader found misattribution by reading the answer or follow-up (e.g. labelling an older survey as the JME). The scorer only sees the first source text; the AI judge should catch these. |
| T3-3 | Gemini 3.5 Flash-Lite | year | Latest | None | No year given. The scoring guide says None; the grader gave Latest. |
| T3-5 | Gemini 3.5 Flash-Lite | year | None | Outdated | '2003 - ??' contains a year (2003), so the rule says Outdated. The grader read it as no year. |
| T3-5 | Gemini 3.5 Flash-Lite | source | Primary | Misattributed | Rule: the answer credits UNICEF (first source named) with a number the key says is Wrong. The grader kept Primary. |

## What this tells us

* Most remaining disagreements come from graders folding source or year problems into the **Number** score (T1-2, T2-4, R3, T3-5). The scorer keeps the three scores separate, which is what the scoring guide asks for.
* **The answer key was wrong for 2 prompts (6 answers)**: P2 (wrong year) and R5 (wrong indicator). The models were right and we marked them Wrong. Several more rows had the wrong year or indicator code recorded. All fixes are logged in `data/test_set/answer_key_corrections.csv`.
* The graders weren't always consistent with the scoring guide. For example, "Latest" was given when no year was stated, and Close was used for answers 10+ points off. A rule-based scorer removes that variation.
