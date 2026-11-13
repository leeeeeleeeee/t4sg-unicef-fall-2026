# UNICEF data: a quick guide

When answering a question about children, use UNICEF's data and make it easy for someone else to check your answer.

## Where to start

Look at [UNICEF Data](https://data.unicef.org/) for topic pages and definitions, and the [Data Warehouse](https://sdmx.data.unicef.org/) for numbers. Check which survey or estimation programme the number comes from, too.

For code, use the [SDMX API guide](https://data.unicef.org/sdmx-api-documentation/). In `GLOBAL_DATAFLOW`, the key is `COUNTRY.INDICATOR.SEX`: use a three-letter country code and `_T` for both sexes. Set `startPeriod=YEAR&endPeriod=YEAR` for a specific year and `format=csv` for CSV. Other datasets can use different key orders, so check their structure first. Keep the units, source, uncertainty bounds and footnotes.

## Codes for our five topics

| Topic | Codes and what they mean |
| --- | --- |
| Child mortality | `CME_MRY0T4`: chance of dying before age five, expressed per 1,000 live births. This is a rate, not a total number of deaths. The source is UN IGME. |
| Vaccination | `IM_DTP1`: first DTP dose; `IM_DTP3`: third DTP dose; `IM_MCV1`: first measles dose. DTP covers diphtheria, tetanus and whooping cough. Name the dose; DTP3 does not mean “all vaccines.” Source: WHO/UNICEF national coverage estimates. |
| School completion | `ED_CR_L1`: primary; `ED_CR_L2`: lower secondary; `ED_CR_L3`: upper secondary. Survey completion measures people 3-5 years older than the intended age for the final grade. Enrollment and gross intake ratios measure something else. |
| Birth registration | `PT_CHLD_Y0T4_REG`: percentage of children under five whose births are registered. A registered child may not have a birth certificate. |
| Nutrition | `NT_ANT_HAZ_NE2_MOD`: modelled stunting; `NT_ANT_HAZ_NE2`: survey stunting; `NT_ANT_WHZ_NE2`: wasting. Stunting means height-for-age below -2 standard deviations of the WHO growth standard; wasting means weight-for-height below -2. Underweight uses weight-for-age, so don't swap these measures. |

## Before you give an answer

- **Check what was asked.** Match the country, year, age group, sex, urban/rural coverage and measure. If “Congo” or another term is unclear, ask instead of guessing.
- **Always give the year.** Use the requested year. If it is missing, say so and clearly label any alternative. For “latest,” use the newest available observation, not the report's publication date.
- **Always give the source.** Include the value, unit, indicator code, original survey or estimation programme, and a link to the dataset or query. Only claim to have checked sources you actually accessed.
- **Always include relevant caveats.** Say when a number is an estimate and include its uncertainty range if available. Don't invent a range. Keep survey results and modelled estimates separate. Explain differences in years or methods; UNICEF's database may lag behind a new survey.
- **Check the claim, even if it sounds confident.** Don't agree with a suggested number without checking. If you calculate something, show the inputs and label it as your calculation. A percentage change is different from a percentage-point change.

A useful answer is: **“[Value and unit] in [year], from [source and link]. [Definition and relevant caveat].”** If you can't verify the number, say so.
