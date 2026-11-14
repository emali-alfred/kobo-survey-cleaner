<p align="center"><img src="assets/icon-1024.png" alt="Survey Cleaner logo" width="140"></p>

<h1 align="center">Survey Cleaner</h1>

<p align="center"><b>Turn a raw KoboToolbox / ODK export, repeat groups included, into ONE analysis-ready file<br>
(Excel, CSV, R, Stata, SPSS or HTML) with answer labels and a data quality report.</b></p>

<p align="center">
  <a href="https://github.com/emali-alfred/kobo-survey-cleaner/releases/latest/download/SurveyCleaner-Setup.exe"><img src="assets/buttons/download-windows.svg" alt="Download for Windows" height="56"></a>
  <a href="https://emali-alfred.github.io/kobo-survey-cleaner/"><img src="assets/buttons/open-web-app.svg" alt="Open the web app" height="56"></a>
  <a href="https://github.com/emali-alfred/kobo-survey-cleaner/releases/latest/download/SurveyCleaner-Android.apk"><img src="assets/buttons/download-android.svg" alt="Download the Android app" height="56"></a>
</p>

<p align="center">Free and open source · your survey data never leaves your device · no GitHub account needed</p>

### How to install (one click, no technical steps)

- **Windows:** click **Download for Windows**, open the downloaded file, and follow the steps.
  Windows may show a blue *"Windows protected your PC"* box because the app is new: click
  **More info**, then **Run anyway**. Then open *Survey Cleaner* from the Start menu.
- **Any device, nothing to install:** click **Open the web app**. On a phone, use your browser's
  menu → *Add to Home screen* to keep it like an app.
- **Android:** click **Android app**, open the downloaded file, and allow *Install unknown apps*
  when your phone asks.

Every version has a **Load demo survey** button so you can try it straight away.

---

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-80%20passing-2ea44f)
![License](https://img.shields.io/badge/license-MIT-blue)

Field teams collecting data on KoboToolbox or ODK spend days on the same cleaning
steps before analysis can start: removing repeated submissions, merging repeat
groups (household members, plots) back onto their households, recoding `-99`
and "don't know", turning answer codes into labels, renaming variables, and
finding the records that don't make sense. `surveyclean` does all of this and
documents every change.

---

## Four steps

| Step | What happens |
| --- | --- |
| **1. Upload** | The data export and, optionally, the XLSForm and a rules file. All common repeat-group layouts are understood: Kobo's Excel export (repeat groups on extra sheets), ODK Central's `.zip` (or its CSV files), and single-sheet CSV exports where each repeat record is a block of columns side by side (`age, gender, age, gender, …` or `members[1]/age, members[2]/age, …`). |
| **2. Reshape** | Choose what one row is: one **submission**, or one **repeat-group record** in *long format* (each member row carries its household's answers). Nested repeats (members → illnesses) work too, and households without members are kept. |
| **3. Preview & rename** | See the cleaned data. Export **all variables** or **selected variables only** (tick boxes, search, select all / none), and optionally rename them, in a table showing each variable's question text from the XLSForm. |
| **4. Name & export** | Type the file name (required), pick the format, get **exactly one file**. |

While cleaning it also:

- removes duplicate submissions (with their repeat-group rows) and Kobo system columns
- tidies names (`hh_info/cattle_owned` → `cattle_owned`)
- recodes missing codes (`-99`, `-88`, `"dk"`, `"refused"`) to real missing values
- converts numbers and dates using the XLSForm, and adds interview length (`duration_min`)
- splits multi-select answers into 0/1 columns
- **flags** outliers (never deletes them) and runs your logic checks
- summarises each enumerator (workload, rushed interviews, missing answers, flags)

In long data, household-level checks count each household once, not once per member.

## Checks & suggestions at every step

Each step shows what looks wrong in the data and what to do about it, most
serious first (✖ problem, ▲ warning, ℹ note). The same list goes into the
Excel export's Data Quality Report sheet, and the command line prints it.

| Step | Examples of what is checked |
| --- | --- |
| **1. Upload** | XLSForm missing or not matching the data; columns not in the form (form-version mix-ups); answer codes not in the choices list; choice options without a label; duplicate submissions; data from several form versions; IDs shared by several submissions; empty columns |
| **2. Reshape** | Submissions without any repeat record; almost-empty records (e.g. refused consent); the same respondent code twice in one submission; exact copies; the same name + phone twice |
| **3. Preview** | Answers that are not valid numbers/dates; impossible ages; negative counts; extreme values; logic-check violations; questions often blank with or without skip logic; very short or very long interviews; enumerators rushing; 'other (specify)' answers to recode; personal data (names, phones, GPS); questions with one answer everywhere |
| **4. Export** | No row ID in the selection; names/phones in a file to be shared; variable names adjusted for Stata/SPSS; labels shortened for Stata; what the chosen format keeps |

## One file, your format

| Format | What's in it | Answer labels | Missing values |
| --- | --- | --- | --- |
| **Excel** `.xlsx` | 4 sheets: the clean data (named after your file), **Outliers**, **Rule Violations**, **Data Quality Report** | label text | empty cells |
| **CSV** `.csv` | clean data only | label text | empty cells |
| **R** `.rds` / `.RData` | clean data only | factors | `NA` |
| **Stata** `.dta` | clean data only | numeric codes + value labels; question text as variable labels | `.` |
| **SPSS** `.sav` | clean data only | numeric codes + value labels; question text as variable labels | system-missing (`.`) |
| **HTML** `.html` | clean data only, as a table | label text | empty cells |

The XLSForm's `choices` sheet maps codes to labels for every `select_one` and
`select_multiple` question (`0` → `No`, `1` → `Yes`; `"1 3"` → `"Maize; Beans"`).
Variable names are made valid automatically for Stata and SPSS (e.g. Stata
reserves `end`, which becomes `end_`), and the app tells you what it changed.

File names are required. Characters Windows does not allow (`\ / : * ? " < > |`)
are removed when you export.

## Windows app

[**Download the latest installer**](https://github.com/emali-alfred/kobo-survey-cleaner/releases/latest/download/SurveyCleaner-Setup.exe)
(always the newest version; older versions are on the
[Releases page](https://github.com/emali-alfred/kobo-survey-cleaner/releases)),
run it, and open *Survey Cleaner* from the Start menu. No Python needed and no
administrator rights; it uninstalls from *Settings → Apps*. It has a
**Load demo survey** button to try everything straight away.

Windows may show "Windows protected your PC" because the installer is not yet
code-signed: click **More info → Run anyway**. The download page lists a
SHA-256 checksum for each file if you want to confirm it is genuine.

To build the installer yourself (needs Python and
[Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
powershell -ExecutionPolicy Bypass -File windows\build.ps1
```

The build checks the bundled program by exporting the demo in all seven formats,
and writes both `SurveyCleaner-Setup-<version>.exe` and `SurveyCleaner-Setup.exe`
(attach both to a release so the download button always gets the newest one).
With a code-signing certificate installed, set `SURVEYCLEAN_SIGN_THUMBPRINT` to its
thumbprint and the build signs the program and the installer.

## Web and Android app

No installation needed: the same cleaner runs in the browser at
**https://emali-alfred.github.io/kobo-survey-cleaner/** (phones included),
with the same four steps. It runs entirely on the device with
[Pyodide](https://pyodide.org), so survey data is never uploaded, and after the
first visit it works offline. Excel, CSV, Stata and HTML export work in the
browser; R and SPSS export need the Windows app (their writers are not
available in browsers).

The web app lives in [`web/`](web/) (`python web/build.py` assembles it), and
[`android/PLAY_STORE.md`](android/PLAY_STORE.md) explains how it is packaged
for Google Play.

## Command line

```bash
pip install .

surveyclean export.xlsx --form form.xlsx --rules rules.yaml \
    --name "Baseline 2026" --format dta --out results
# -> results/Baseline 2026.dta   (one file)

surveyclean export.xlsx --list-tables                 # main table + repeat groups
surveyclean export.xlsx --level hh_members --name members --format xlsx
surveyclean export.xlsx --name x --format csv --rename hh_size=household_size county=district
surveyclean --demo --name demo --open                 # try the built-in synthetic survey
```

`--format` is one of `xlsx` (default), `csv`, `rds`, `RData`, `dta`, `sav`,
`html`. `--keep VAR …` exports only those variables. `--codes` keeps the answer codes instead of labels. The checks & suggestions are printed after each run (`--all-checks` also prints the notes). Run
`surveyclean-gui` for the desktop window.

## Example

The `examples/` folder holds a **synthetic** livestock household survey: 124
submissions and 754 household members in a repeat group (randomly generated, no
real respondents) with typical field problems planted in it:

```text
$ surveyclean examples/sample_raw_export.xlsx --form examples/sample_form.xlsx \
      --rules examples/rules.yaml --name "Livestock survey demo" --out examples/output

Submissions: 124 in, 120 out (4 duplicates removed), one row per 'hh_members' record (725 rows)
Flags: 3 possible outliers, 10 rule violations
Saved: examples/output/Livestock survey demo.xlsx
```

| Problem planted | Found by |
| --- | --- |
| 4 duplicate submissions (and their members) | Duplicate removal |
| `-99`, `-88` and `"dk"` in ages and income | Missing-code recoding |
| `"twelve"` typed into household size | Type conversion |
| Household head aged 7; a member aged 150 | Rules `head_age_plausible`, `member_age_plausible` |
| Household with 0 members | Rule `household_not_empty` (kept as one row with empty member columns) |
| More cattle sold than owned (2); milk with no cattle (2) | Rules `sold_not_more_than_owned`, `milk_needs_cattle` |
| A 310-head herd and KES 2.5 million monthly income | Outlier flags |
| One enumerator with 3 interviews under 10 minutes | Rule `interview_length` + enumerator summary |

Result: [`examples/output/Livestock survey demo.xlsx`](examples/output/)

## Writing logic checks

Rules live in a simple YAML file. Each `check` describes what a **valid**
record looks like, using the cleaned column names:

```yaml
rules:
  - name: sold_not_more_than_owned
    check: "cattle_sold_12m <= cattle_owned"
    message: "Cattle sold in 12 months is more than cattle owned"

  - name: member_age_plausible
    check: "member_age >= 0 and member_age <= 110"
```

Records with a missing answer are not counted as breaking a rule, a rule with a
typo is reported instead of stopping the run, and a rule about a repeat group
that is not in the chosen row level is skipped with a note.

## Use it from Python or Jupyter

```python
import surveyclean

s = surveyclean.inspect("export.xlsx")          # tables: main + repeat groups
res = surveyclean.run("export.xlsx", form="form.xlsx", rules="rules.yaml", level="hh_members")
res.data.head()                                  # clean long-format DataFrame
res.rule_violations, res.outliers                # records to follow up
path, notes = surveyclean.export_file(res, "results", "Baseline 2026", "sav",
                                      rename={"hh_size": "household_size"})
```

## Development

```bash
pip install ".[dev]"
python examples/make_sample_data.py      # regenerate the synthetic survey
pytest                                   # 79 tests, including a walk through the desktop window
```

```text
surveyclean/
├── advisor.py    # checks & suggestions at each step
├── tables.py     # reads exports with repeat groups; reshapes to long format
├── xlsform.py    # reads the XLSForm (questions, types, repeats, choice labels)
├── clean.py      # individual cleaning and checking steps
├── pipeline.py   # runs the steps in order
├── export.py     # writes the single output file in the chosen format
├── report.py     # the data quality report (Excel sheet)
├── cli.py        # command line interface
├── gui.py        # desktop window (surveyclean-gui)
└── demo/         # synthetic demo files used by --demo and the apps
windows/          # Windows installer build (PyInstaller + Inno Setup)
web/              # browser / Android app (runs the package with Pyodide)
android/          # Google Play publishing guide and store listing
assets/           # logo, Play Store icon and feature graphic
examples/         # synthetic demo survey, form, rules and output
tests/            # pytest suite
```

---

## About

Built by **Alfred Kombo Emali**, an agricultural and applied economist and data
analyst in Nairobi, Kenya, working on livestock, gender and socioeconomic research.

**Need survey data cleaned, analysed or turned into a report?**
[LinkedIn](https://www.linkedin.com/in/alfred-kombo) · [emalialfred8@gmail.com](mailto:emalialfred8@gmail.com)
