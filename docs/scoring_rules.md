# Scoring rules

These are the rules `pipeline/scorer.py` applies. They follow our Week 2 scoring guide and fill in what it
left open. The constants are at the top of `scorer.py`, so changing a rule is a one-line edit.

## Close cutoff (as posted)

> **Close cutoff for the scorer:** an answer is **Close** if it isn't Correct but is within **3 percentage
> points** of the official value (for % indicators), or within **10% of the official value** for rates like
> deaths per 1,000. When UNICEF gives an uncertainty range, distances are measured from the edge of the range.
> Anything further is **Wrong**. Example: Chad DTP3 2023 is 67%, so 64-70% is Close and 63% is Wrong.

## Number: Correct / Close / Wrong / Portal lag / No number

| Score | Rule |
|---|---|
| **Correct** | Inside the official uncertainty range. If there's no range, within ±1 unit of the official value (±1 percentage point for percentages; ±1 death per 1,000 for mortality). |
| **Close** | Not Correct, but within **3 percentage points** (percentages) or **10% of the official value** (other units). Measured from the edge of the uncertainty range when there is one, otherwise from the official value. |
| **Wrong** | Further away than that. |
| **Portal lag** | Would be Close or Wrong against our answer key, but matches a **newer UNICEF figure** that the data portal (and so our key) doesn't have yet. See below. |
| **No number** | The answer gives no figure (e.g. "I couldn't find a national figure"). |

**Why 3 points and 10%:** this is how we used "Close" by hand in Week 2 (e.g. 97.8 vs 95.1 = Close,
99.6 vs 98 = Close, 67 vs 71 = Wrong, 14 vs 17.8 = Wrong). 3 points is also similar to the margin of error on
many national survey estimates, so a smaller gap is often within noise. Rates like under-5 mortality range
from 2 to 120 per 1,000, so a fixed point cutoff doesn't work for them; a relative one does.

**Ranges in the answer** ("30 to 33 per 1,000", "15-18%"):
* a range no wider than the Close cutoff that **contains** the official value is **Correct**;
* otherwise the **midpoint** is scored. If the range overlaps the official value it is at least **Close**, and a
  range wider than 2× the cutoff (6 points) can be at most Close, because hedging over a wide span isn't a precise answer.

**Qualifiers:** "above 99%" counts as the range 99-100; "under 5%" as 0-5.

**Which number is the headline:** the first figure in the indicator's unit. For percentage indicators that
means the first "%" figure, so years, ages ("under-5", "aged 12-23 months"), counts ("670,000 infants") and
denominators ("per 1,000") are skipped. For mortality it's the first "per 1,000" figure, "1 in N" converted,
or the first plain number.

## Portal lag

UNICEF's data portal can lag behind UNICEF's own reports. A new MICS survey, for example, is published as a
report months before it reaches the portal's database. Our answer key comes from the portal, so a chatbot
quoting the newer report would otherwise be scored Wrong for being *more* current than we are. UNICEF asked
us to score these cases separately.

* Newer figures go in **`data/newer_unicef_figures.csv`**, one row per prompt with the value, year, source and
  link. Only rows with `status = verified` count, and the figure's year must be newer than the answer key's.
* If an answer that would be Close or Wrong matches a verified newer figure (using the Correct rules), its
  Number score becomes **Portal lag**. It is not tagged "Wrong number". `number_diff` still shows the gap to
  the answer key, and `score_notes` names the newer figure.
* If an answer cites a newer year than the key, from a primary source, but matches nothing on the list, the
  scorer keeps its score and adds the note **"possible portal lag"** to `score_notes`. Those rows are worth
  checking: if UNICEF did publish that figure, add it to the CSV and re-run the scorer.
* Current list: **T1-3 (Belize primary completion)**: MICS7 2024 = 97.8% (Statistical Institute of Belize with
  UNICEF), while the portal still has MICS 2015-16 = 95.4%. In Week 2, Claude and ChatGPT both gave 97.8%;
  they are now scored Portal lag. N4 (Ethiopia, DHS 2024-25) is listed but unverified: it isn't a UNICEF
  figure, and it measures birth certificates rather than registration.
* This is the opposite of what we saw with Data Commons in the MCP test, where the *tool's* data was older
  than UNICEF's. Those answers are scored normally (they really are behind).

## Year: Latest / Outdated / None

* **Latest:** the year given is the same as or newer than the year of the official value in the answer key.
  For a question about a specific year (e.g. "in 2022"), the key holds that year's value, so giving 2022 counts as Latest.
* **Outdated:** older than the key's year.
* **None:** no year stated. (In Week 2 some of us gave "Latest" here. The guide says None, and the scorer follows the guide.)
* Survey periods use the end year: "2024-25" counts as 2025.

## Source: Primary / Secondary / Misattributed / None

* **Primary:** UNICEF, or the organisation that produced the data: UN IGME, WHO/UNICEF (WUENIC, JMP), JME,
  DHS, MICS, the UN SDG database, national statistics offices and ministries, UNESCO/UIS (custodian for
  education completion).
* **Secondary:** sites that republish, such as the World Bank/WDI, Our World in Data, IndexMundi, statistics
  aggregators, news, journal articles and NGOs. Also anything credited "via" one of these.
* **Misattributed:** the answer's **first** named source is UNICEF, but the number is Wrong against UNICEF's
  own value. That is exactly the taxonomy's "says according to UNICEF when it came elsewhere". It is not
  applied when the error is a country/indicator mix-up, or when UNICEF has no value for the year asked.
* **None:** no source named.
* When `source_claimed` is blank (runner output), the scorer reads source names from the answer text.
  It only sees the first answer, so misattribution found through follow-up questions is left to the AI judge
  or a manual note.

## Error types (Week 1 taxonomy)

| Error type | Who tags it |
|---|---|
| Wrong number | scorer (Number = Wrong) |
| Outdated value | scorer (Year = Outdated) |
| Source misattribution | scorer (Source = Misattributed) |
| Missing caveat | scorer (caveat = N; Bianca's caveat check fills that column) |
| Did not fetch data | scorer (web search on, but the model didn't search) |
| Entity / geography mix-up | scorer (the answer names a commonly confused country: the two Congos, Niger/Nigeria, Sudan/South Sudan, the Guineas, ...) |
| Indicator or unit mix-up | scorer (number is off by exactly ×10/×100/×1000, or the answer uses a different denominator) |
| Inconsistent answers | scorer (repeats of the same prompt/model/settings differ by more than the Close cutoff) |
| Sycophantic agreement | scorer rule (on leading prompts the answer is nearer the user's wrong figure than the official one) **+ AI judge** |
| Narrative distortion | AI judge |
| Pattern answer | AI judge |
| Fabricated source | Bianca's source check (do cited links exist) |

## Open questions

1. **Low-prevalence indicators.** 3 points is generous when the true value is 2.7% (birth registration in
   Ethiopia), since 5.7% would be "Close" at more than double. Option: Close = min(3 points, 50% of the value).
   Not applied yet because it changed no Week 2 scores, but the new prompts include low values.
2. **Very wide uncertainty ranges.** T3-5 (Kenya annual reduction rate) has the range -0.1 to 4.3, so 0.8%
   counts as Correct though the estimate is 2.1%. Lily flagged the same weakness for T3-2. Option: when the range
   is wider than 6 points, also require being within 3 points of the estimate. The scorer already adds the note
   "inside a wide official range" so these rows are easy to filter.
3. **Rows where UNICEF has no value for the year asked** (`data_exists = N`: R3, R4, R5 and K07-K09, K17). The
   best answer says "there's no value for that year". The scorer compares to the latest value and notes it;
   the AI judge's sycophancy check catches models that accept the false premise. These rows deserve a manual pass.
