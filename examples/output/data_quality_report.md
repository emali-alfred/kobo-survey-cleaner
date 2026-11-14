# Livestock household survey: data quality report (synthetic demo)
_Generated 2026-11-14 18:47_

## Summary

| | Count |
| --- | --- |
| Records received | 124 |
| Duplicate submissions removed | 4 |
| Records after cleaning | 120 |
| Columns received → after cleaning | 24 → 27 |
| System columns dropped | 7 |
| Missing codes (-99, "don't know", ...) recoded | 6 |
| Values that could not be read as numbers/dates | 1 |
| Multi-select answers split into 0/1 columns | 5 |
| Label columns added | 4 |
| Possible outliers to check | 3 |
| Consistency rule violations | 9 |
| Median interview length (minutes) | 46.5 |
| Enumerators | 5 |

## Consistency checks
Records that break a logic rule. These usually need a call-back to the enumerator.

| record | rule | detail |
| --- | --- | --- |
| 412a5108-9a6a-47b8-8fa3-91a959a297db | head_age_plausible | Household head age should be between 15 and 110 |
| 79721b4d-671d-4986-9894-822f7c08c9be | household_not_empty | Household must have at least one member |
| 4ff57877-ae11-44e4-859f-e4478eaeee0d | sold_not_more_than_owned | Cattle sold in 12 months is more than cattle owned |
| 0169a835-fd4d-4157-bd47-9c5549a63b0f | sold_not_more_than_owned | Cattle sold in 12 months is more than cattle owned |
| 7b913861-45ed-451b-a66b-d94c871ba8a2 | milk_needs_cattle | Milk reported but no cattle owned |
| 3f907663-9f40-4cef-8095-098fbd33fb8f | milk_needs_cattle | Milk reported but no cattle owned |
| 643dbee6-4f64-424d-bbe5-4ae38f3e1c90 | interview_length | Interview shorter than 10 minutes |
| 2cf295e0-1ce1-43a3-8795-8ecd0dda63f4 | interview_length | Interview shorter than 10 minutes |
| 01550a97-e607-43e7-b49a-2ec47ddd9ac0 | interview_length | Interview shorter than 10 minutes |

## Possible outliers
Extreme values are flagged, not deleted. Confirm them before analysis.

| record | column | value | expected_range |
| --- | --- | --- | --- |
| 7abc3e49-a5fb-45f8-9431-80ec0de37ba4 | cattle_owned | 310 | 0 to 19 |
| 4ff57877-ae11-44e4-859f-e4478eaeee0d | cattle_sold_12m | 10 | 0 to 8 |
| 7a579db5-8d07-4e4a-b385-107186b07693 | monthly_income_kes | 2,500,000 | 3,800 to 60,300 |

## Enumerator summary (by `enumerator`)
Workload, speed, missing answers and flags per enumerator, most flags first. Use it to target support and call-backs.

| enumerator | records | missing_pct | median_minutes | under_10_min | duplicates | outliers | rule_violations | flags_per_10_records |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| enum_03 | 23 | 0.7 | 42.0 | 0 | 2 | 2 | 4 | 2.6 |
| enum_04 | 21 | 0.8 | 43.0 | 3 | 0 | 0 | 3 | 1.4 |
| enum_05 | 30 | 0.6 | 46.5 | 0 | 0 | 1 | 2 | 1.0 |
| enum_01 | 26 | 0.0 | 48.5 | 0 | 2 | 0 | 0 | 0.0 |
| enum_02 | 20 | 0.4 | 51.0 | 0 | 0 | 0 | 0 | 0.0 |

## Missing data
Share of missing answers per question (after recoding missing codes).

| column | missing_pct |
| --- | --- |
| hh_head_age | 2.5 |
| monthly_income_kes | 2.5 |
| hh_size | 0.8 |

## Missing codes recoded

| column | values_recoded |
| --- | --- |
| hh_head_age | 3 |
| monthly_income_kes | 3 |

## Duplicate submissions removed

| _uuid | _submission_time | enumerator |
| --- | --- | --- |
| 3465f13e-4336-47c8-9cd3-96d5eab513a1 | 2026-03-09T17:35:00 | enum_03 |
| 461f6869-caa2-45b2-81ce-9b67387fb91a | 2026-03-07T17:38:00 | enum_01 |
| 461f6869-caa2-45b2-81ce-9b67387fb91a | 2026-03-07T17:38:00 | enum_01 |
| 25557557-435e-4298-b128-c6bc304721c9 | 2026-03-09T16:05:00 | enum_03 |

## Values that could not be converted
Answers that are not valid numbers or dates were set to missing.

| column | values |
| --- | --- |
| hh_size | 1 |
