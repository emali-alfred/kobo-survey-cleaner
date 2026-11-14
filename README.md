<p align="center"><img src="assets/icon-1024.png" alt="Survey Cleaner logo" width="140"></p>

# surveyclean: KoboToolbox / ODK survey data cleaner

**Turn a raw survey export into analysis-ready data, plus a data quality report you can share with your team, in one command.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-25%20passing-2ea44f)
![License](https://img.shields.io/badge/license-MIT-blue)

Field teams collecting data on KoboToolbox or ODK spend days on the same cleaning
steps before analysis can start: removing repeated submissions, recoding `-99`
and "don't know", renaming `group/subgroup/question` columns, splitting
multi-select answers, and finding the records that don't make sense.
`surveyclean` does all of this automatically and documents every change.

---

## What it does

| Step | What happens |
| --- | --- |
| **Remove system columns** | Drops Kobo metadata (`__version__`, `_validation_status`, `formhub/uuid`, ...) |
| **Tidy column names** | `hh_info/livestock/cattle_owned` → `cattle_owned`; Kobo's own split columns `livestock/kept/cattle` → `kept__cattle` |
| **Remove duplicates** | Drops repeated submissions of the same form (same `_uuid`) |
| **Recode missing codes** | `-99`, `-99.0`, `-88`, `"dk"`, `"refused"` → real missing values |
| **Fix data types** | Numbers and dates are converted using the XLSForm (times stay in local time), and unreadable entries (e.g. `"twelve"`) are counted |
| **Interview length** | `duration_min` is added from the form's `start` and `end` |
| **Split multi-select answers** | `"cattle goats"` → `livestock_kept__cattle = 1`, `livestock_kept__goats = 1` |
| **Add labels** | `county = 2` → `county_label = Narok` |
| **Flag outliers** | Extreme values are **flagged for checking, never deleted** |
| **Run logic checks** | Your own rules, e.g. *cattle sold ≤ cattle owned* |
| **Enumerator summary** | Records, median interview length, rushed interviews, missing rate and flags per enumerator |
| **Write a report** | HTML and Markdown reports, an Excel workbook (one sheet per table) and CSVs of every flagged record |

## Example result

The `examples/` folder contains a **synthetic** livestock household survey of 124
records (randomly generated, with no real respondents) with typical field problems
planted in it. Running the cleaner on it:

```text
$ surveyclean examples/sample_raw_export.csv --form examples/sample_form.xlsx \
      --rules examples/rules.yaml --out examples/output

Records: 124 in, 120 out (4 duplicates removed)
Flags: 3 possible outliers, 9 rule violations
```

It catches every problem that was planted:

| Problem planted | Found by |
| --- | --- |
| 4 duplicate submissions | Duplicate removal |
| `-99`, `-88` and `"dk"` in age and income | Missing-code recoding (6 values) |
| `"twelve"` typed into household size | Type conversion |
| Household head aged 7 | Rule `head_age_plausible` |
| Household with 0 members | Rule `household_not_empty` |
| More cattle sold than owned (2 records) | Rule `sold_not_more_than_owned` |
| Milk produced with no cattle (2 records) | Rule `milk_needs_cattle` |
| A 310-head herd and KES 2.5 million monthly income | Outlier flags |
| One enumerator with 3 interviews under 10 minutes | Rule `interview_length` + enumerator summary |

See the full report: [`examples/output/data_quality_report.md`](examples/output/data_quality_report.md)

## Quick start

```bash
git clone https://github.com/emali-alfred/kobo-survey-cleaner.git
cd kobo-survey-cleaner
pip install .

surveyclean your_export.csv --form your_xlsform.xlsx --rules rules.yaml --out output --open
surveyclean --demo --open     # try it on the built-in synthetic survey
```

Prefer not to use the command line? Run **`surveyclean-gui`** for a small
desktop window: pick your files, click *Clean data*, then *Open report*.
It has a *Load demo survey* button too.

Output folder:

```text
output/
├── clean_data.csv            # analysis-ready data
├── clean_data.xlsx           # the same, plus a sheet per table below
├── data_quality_report.html  # summary for the team / client (open in a browser)
├── data_quality_report.md    # the same report as Markdown
├── rule_violations.csv       # records to call back
├── outliers.csv              # values to confirm
└── enumerator_summary.csv    # only when an enumerator column is found
```

The enumerator column is detected automatically (`enumerator`, `username`,
`_submitted_by`, `deviceid`, ...) or set with `--enumerator-col`.

The `--form` and `--rules` options are optional. Without the form, the
cleaner still removes duplicates, tidies names, recodes missing codes and
flags outliers.

## Web and Android app

No installation needed: the same cleaner runs in the browser at
**https://emali-alfred.github.io/kobo-survey-cleaner/** (phones included).
It runs entirely on the device with [Pyodide](https://pyodide.org), so survey
data is never uploaded, and after the first visit it works offline. In Chrome
on Android, choose *Install app* to add it to the home screen.

The web app lives in [`web/`](web/) (`python web/build.py` assembles it), and
[`android/PLAY_STORE.md`](android/PLAY_STORE.md) explains how it is packaged
for Google Play.

## Writing logic checks

Rules live in a simple YAML file. Each `check` describes what a **valid**
record looks like, using the cleaned column names:

```yaml
rules:
  - name: sold_not_more_than_owned
    check: "cattle_sold_12m <= cattle_owned"
    message: "Cattle sold in 12 months is more than cattle owned"

  - name: interview_length
    check: "(end - start).dt.total_seconds() >= 600"
    message: "Interview shorter than 10 minutes"
```

Records with a missing answer are not counted as breaking a rule (missing
data is reported separately), and a rule with a typo is reported in the output
instead of stopping the run.

## Use it from Python or Jupyter

```python
import surveyclean

res = surveyclean.run("export.csv", form="form.xlsx", rules="rules.yaml")
res.data.head()            # clean DataFrame
res.rule_violations        # records to follow up
res.outliers               # values to confirm
surveyclean.write_outputs(res, "output")
```

## Try the demo

```bash
pip install ".[dev]"
python examples/make_sample_data.py      # regenerate the synthetic survey
surveyclean examples/sample_raw_export.csv --form examples/sample_form.xlsx \
    --rules examples/rules.yaml --out examples/output
pytest                                   # 25 tests
```

## Project structure

```text
surveyclean/
├── xlsform.py    # reads the XLSForm (questions, types, choice labels)
├── clean.py      # individual cleaning and checking steps
├── pipeline.py   # runs the steps in order
├── report.py     # writes the clean data, HTML/Markdown report and Excel workbook
├── cli.py        # command line interface
├── gui.py        # desktop window (surveyclean-gui)
└── demo/         # synthetic demo files used by --demo and the window
web/              # browser / Android app (runs the package with Pyodide)
android/          # Google Play publishing guide and store listing
assets/           # logo, Play Store icon and feature graphic
examples/         # synthetic demo survey, form, rules and output
tests/            # pytest suite
```

## Roadmap

- [ ] Repeat groups (household member rosters) exported as separate sheets
- [ ] Stata `.dta` and SPSS `.sav` export with variable and value labels
- [x] Enumerator-level quality summary (speed, missing rate, flags per enumerator)
- [x] HTML report
- [ ] Charts in the HTML report

---

## About

Built by **Alfred Kombo Emali**, an agricultural and applied economist and data
analyst in Nairobi, Kenya, working on livestock, gender and socioeconomic research.

**Need survey data cleaned, analysed or turned into a report?**
[LinkedIn](https://www.linkedin.com/in/alfred-kombo) · [emalialfred8@gmail.com](mailto:emalialfred8@gmail.com)
