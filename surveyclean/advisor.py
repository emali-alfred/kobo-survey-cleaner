"""Checks & suggestions: find anomalies at each step and say what to do.

Every check returns `Finding`s with a severity:
  problem  - very likely wrong; fix before analysis
  warning  - worth checking
  note     - good to know; usually nothing to do

Steps:
  check_upload   the files: form match, codes not in the form, duplicates, empty columns, versions
  check_reshape  the chosen row level: records without answers, duplicate codes, copies, missing records
  check_cleaned  the cleaned data: unreadable values, outliers, rules, missing data, interview length,
                 enumerators, 'other' answers, personal data
  check_export   the chosen file: left-out IDs, renamed variables, long labels, what the format keeps
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import pandas as pd

from .clean import DEFAULT_MISSING_CODES, short_name
from .tables import KEY, PARENT_KEY, Survey
from .xlsform import Form, code_key

SEVERITY_ORDER = {"problem": 0, "warning": 1, "note": 2}
STEP_NAMES = {"upload": "1 Upload", "reshape": "2 Reshape", "preview": "3 Preview", "export": "4 Export"}

_ID_LIKE = re.compile(r"(^|_)(id|code)$|^id_", re.IGNORECASE)
_AGE = re.compile(r"(^|_)age($|_)", re.IGNORECASE)
_NAME = re.compile(r"(^|_)(name|names|first_?name|surname|last_?name)($|_)", re.IGNORECASE)
_NOT_PERSON_NAME = re.compile(r"instance|file|user|form|village|venue|county|group|school|place", re.IGNORECASE)
_PHONE = re.compile(r"phone|mobile|tel(ephone)?($|_)|msisdn", re.IGNORECASE)
_GPS = re.compile(r"^(?!.*(altitude|precision|accuracy)).*(gps|geopoint|latitude|longitude)", re.IGNORECASE)
_OTHER = re.compile(r"(_other|other_|_oth|_specify)$|^other_", re.IGNORECASE)
_MISSING = {str(c).strip().lower() for c in DEFAULT_MISSING_CODES}
# Columns Kobo/ODK add that are not questions.
_SYSTEM = re.compile(r"^(_|meta/|formhub/)|^(instance_?id|instance_?name|key|parent_key|submissiondate|"
                     r"submitterid|submittername|attachmentspresent|attachmentsexpected|status|"
                     r"reviewstate|deviceid|edits|formversion)$", re.IGNORECASE)


@dataclass
class Finding:
    step: str
    severity: str
    title: str
    detail: str = ""
    suggestion: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 3))


def _few(items, n: int = 5) -> str:
    items = [str(i) for i in items]
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def _question_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not str(c).startswith("__") and not _SYSTEM.search(str(c))]


def _is_missing_code(v) -> bool:
    return str(v).strip().lower() in _MISSING


# --- step 1: the files ----------------------------------------------------------------

def check_upload(survey: Survey, form: Form | None = None) -> list[Finding]:
    out: list[Finding] = []
    form = form or Form()
    main = survey.tables[survey.main].data

    for note in survey.notes:
        out.append(Finding("upload", "note", "Repeat group stored side by side was stacked", note,
                           "Nothing to do. In step 2, choose this repeat group to get one row per record."))

    if not form.questions:
        out.append(Finding("upload", "warning", "No XLSForm added",
                           "Without the form, answer codes stay as codes (1, 2 …), numbers and dates are kept "
                           "as text, and skip logic is unknown.",
                           "Add the XLSForm (.xlsx) used to collect this data in step 1."))

    # Columns of every table, by cleaned name.
    data_cols: dict[str, str] = {}
    for t in survey.tables.values():
        for c in _question_cols(t.data):
            base = c.rsplit("/", 1)[0] if "/" in c and c.rsplit("/", 1)[0] in t.data.columns else c
            data_cols.setdefault(short_name(base), t.name)

    if form.questions:
        meta_types = {"start", "end", "today", "deviceid", "username", "phonenumber", "audit",
                      "simserial", "subscriberid", "calculate", "hidden"}
        form_names = set(form.questions)
        matched = form_names & set(data_cols)
        if not matched:
            out.append(Finding("upload", "problem", "The XLSForm does not match this data",
                               "None of the form's questions appear as columns in the export.",
                               "Check you chose the form used to collect this data (same project and version)."))
        else:
            extra = sorted(set(data_cols) - form_names)
            if extra:
                out.append(Finding("upload", "warning", f"{len(extra)} data column(s) are not in the XLSForm",
                                   f"Not in the form: {_few(extra, 8)}.",
                                   "Usually the data came from an older or newer form version. Use the form "
                                   "version that matches the export, or check these columns by hand."))
            unused = sorted(q for q in form_names - set(data_cols)
                            if form.questions[q].qtype not in meta_types)
            if unused:
                out.append(Finding("upload", "note", f"{len(unused)} form question(s) have no column in the data",
                                   f"Missing: {_few(unused, 8)}.",
                                   "Normal for questions nobody was asked. If they should be there, check "
                                   "the export settings in Kobo/ODK (e.g. 'include all versions')."))

        # Codes that are not in the choices sheet / options without a label.
        for q in form.of_type("select_one", "select_multiple"):
            labels = form.choice_labels(q.name)
            table = data_cols.get(q.name)
            if not labels or table is None:
                continue
            df = survey.tables[table].data
            cols = [c for c in _question_cols(df) if short_name(c) == q.name]
            seen: set[str] = set()
            for c in cols:
                vals = df[c].dropna().astype(str)
                if q.qtype == "select_multiple":
                    vals = pd.Series([v for s in vals for v in s.split()], dtype=object)
                seen |= {code_key(v) for v in vals if v.strip() and not _is_missing_code(v)}
            unknown = sorted(seen - set(labels))
            if unknown:
                out.append(Finding("upload", "warning", f"'{q.name}': answer codes not in the XLSForm",
                                   f"Codes {_few(unknown)} have no label in the '{q.list_name}' choices list.",
                                   "They are kept as codes. Add them to the choices sheet, or correct the "
                                   "entries if they are typing errors."))
        for lst, codes in form.unlabelled.items():
            used_by = [q.name for q in form.questions.values() if q.list_name == lst]
            if used_by:
                out.append(Finding("upload", "warning", f"Choices list '{lst}': option(s) without a label",
                                   f"Option(s) {_few(codes)} have no label, so they will show as codes "
                                   f"in {_few(used_by, 3)}.",
                                   "Add the label in the XLSForm choices sheet (e.g. 'Other (specify)')."))

    if "_uuid" in main.columns:
        n = int(main["_uuid"].notna().sum() - main["_uuid"].dropna().nunique())
        if n:
            out.append(Finding("upload", "warning", f"{n} duplicate submission(s)",
                               "Some submissions were sent more than once (same _uuid).",
                               "They are removed automatically in step 2, keeping the first copy."))

    for vcol in ("__version__", "_version"):
        if vcol in main.columns and main[vcol].nunique() > 1:
            out.append(Finding("upload", "note", f"Data from {main[vcol].nunique()} form versions",
                               "Questions added or changed between versions may be empty for earlier submissions.",
                               "Use the latest XLSForm; check questions with many missing answers in step 3."))
            break

    for c in _question_cols(main):
        if _ID_LIKE.search(short_name(c)) and main[c].notna().any():
            used = main[c].dropna()
            if used.duplicated().any():
                out.append(Finding("upload", "note", f"'{short_name(c)}' repeats across submissions",
                                   f"{used.nunique()} values are shared by {len(used)} submissions.",
                                   "Expected if one group/household was entered in several submissions (e.g. "
                                   "two enumerators each covering part of a group). Otherwise check for "
                                   "re-submissions or mistyped IDs."))

    empty = sorted({short_name(c) for t in survey.tables.values() for c in _question_cols(t.data)
                    if t.data[c].isna().all()})
    if empty:
        out.append(Finding("upload", "note", f"{len(empty)} column(s) are empty everywhere",
                           f"No answers at all: {_few(empty, 8)}.",
                           "Leave them out with 'Selected variables only' in step 3."))
    return _sorted(out)


# --- step 2: the row level ------------------------------------------------------------------

def check_reshape(survey: Survey, level: str, form: Form | None = None) -> list[Finding]:
    out: list[Finding] = []
    if level not in survey.tables or level == survey.main:
        if survey.repeats and level == survey.main:
            out.append(Finding("reshape", "note", "Repeat groups are summarised, not listed",
                               f"With one row per submission, {_few([t.name for t in survey.repeats])} "
                               "become count columns (n_<group>).",
                               "To get one row per member / participant, choose the repeat group instead."))
        return out

    main = survey.tables[survey.main].data
    kept = main
    if "_uuid" in main.columns:
        kept = main[~(main["_uuid"].notna() & main["_uuid"].duplicated())]
    path = survey.path_to(level)
    parent_keys = set(kept[KEY]) if KEY in kept.columns else set()
    child = survey.tables[path[1]].data
    child = child[child[PARENT_KEY].isin(parent_keys)] if parent_keys else child
    parent = kept
    for name in path[2:]:  # follow nested repeats down to the chosen level
        parent = child
        t = survey.tables[name].data
        child = t[t[PARENT_KEY].isin(set(child[KEY]))]
    rec = child
    label = level

    # Parents without any record at this level.
    no_records = parent[~parent[KEY].isin(set(rec[PARENT_KEY]))] if KEY in parent.columns else parent.iloc[0:0]
    if len(no_records):
        ids = no_records["_uuid"].tolist() if "_uuid" in no_records.columns else no_records[KEY].tolist()
        out.append(Finding("reshape", "note", f"{len(no_records)} {path[-2]} row(s) have no '{label}' records",
                           f"They are kept as one row each with the '{label}' columns empty "
                           f"(e.g. {_few(ids, 3)}).",
                           "Fine if nobody was listed there; otherwise check those submissions."))

    qcols = [c for c in _question_cols(rec)]
    if qcols:
        answered = rec[qcols].notna().sum(axis=1)
        limit = max(1, int(len(qcols) * 0.1))
        thin = rec[answered <= limit]
        if len(thin):
            only = thin[qcols].notna().sum().sort_values(ascending=False)
            only = [short_name(c) for c, n in only.items() if n][:3]
            out.append(Finding("reshape", "warning", f"{len(thin)} '{label}' record(s) are almost empty",
                               f"They have {limit} answer(s) or fewer"
                               + (f", mostly '{', '.join(only)}'." if only else "."),
                               "Often a refused consent or an entry started by mistake. Keep them if you report "
                               "refusals; otherwise leave them out in your analysis (e.g. filter on consent)."))

        # The same record code twice under one parent.
        for c in qcols:
            if _ID_LIKE.search(short_name(c)):
                d = rec[[PARENT_KEY, c]].dropna()
                dup = d[d.duplicated(keep=False)]
                if len(dup):
                    codes = sorted(set(dup[c]))
                    out.append(Finding("reshape", "problem",
                                       f"'{short_name(c)}' used twice within one submission",
                                       f"Code(s) {_few(codes)} appear more than once in the same submission "
                                       f"({dup[PARENT_KEY].nunique()} submission(s)).",
                                       "Each record should have its own code. Check with the enumerator and "
                                       "correct the code in Kobo/ODK."))

        # Exact copies (only meaningful with enough answers to tell records apart)
        # and the same person twice.
        rich = rec[answered >= 5]
        copies = rich[rich.duplicated(subset=qcols + [PARENT_KEY], keep="first")] if len(qcols) >= 5 else rich.iloc[0:0]
        if len(copies):
            out.append(Finding("reshape", "warning", f"{len(copies)} '{label}' record(s) are exact copies",
                               "Every answer is identical to another record in the same submission.",
                               "Probably entered twice; remove the copy in Kobo/ODK or after export."))
        names = [c for c in qcols if _NAME.search(short_name(c)) and not _NOT_PERSON_NAME.search(short_name(c))]
        phones = [c for c in qcols if _PHONE.search(short_name(c))]
        if names and phones:
            key = rec[[names[0], phones[0]]].dropna()
            key = pd.DataFrame({"n": key[names[0]].str.strip().str.lower(),
                                "p": key[phones[0]].astype(str).str.replace(r"\D", "", regex=True)})
            twice = key[key.duplicated(keep=False)]
            if len(twice):
                out.append(Finding("reshape", "warning", "The same person may be entered twice",
                                   f"{twice.drop_duplicates().shape[0]} name + phone combination(s) appear more "
                                   "than once.",
                                   "Check whether they are the same person interviewed twice."))
    return _sorted(out)


# --- step 3: the cleaned data ------------------------------------------------------------------

def check_cleaned(res, short_minutes: float = 10.0, long_minutes: float = 240.0) -> list[Finding]:
    out: list[Finding] = []
    d = res.data
    form = res.form

    if len(res.duplicates):
        out.append(Finding("preview", "note", f"{len(res.duplicates)} duplicate submission(s) removed",
                           "The first copy of each was kept.", "Nothing to do."))
    for col, n in sorted(res.type_failures.items(), key=lambda kv: -kv[1]):
        out.append(Finding("preview", "problem", f"'{col}': {n} answer(s) could not be read",
                           "They are not valid numbers/dates (e.g. 'twelve' in a number question) and were "
                           "set to missing.",
                           "Correct them in Kobo/ODK, or add a constraint to the question so it cannot happen."))
    if res.recoded_missing:
        total = sum(res.recoded_missing.values())
        out.append(Finding("preview", "note", f"{total} missing code(s) turned into missing values",
                           "Codes such as -99, -88, 'dk' and 'refused' in: "
                           + _few(sorted(res.recoded_missing, key=lambda c: -res.recoded_missing[c]), 6) + ".",
                           "Nothing to do, unless you need to tell 'don't know' and 'refused' apart in the "
                           "analysis: then keep a copy of the raw export."))
    if len(res.outliers):
        top = res.outliers["column"].value_counts()
        out.append(Finding("preview", "warning", f"{len(res.outliers)} extreme value(s) to confirm",
                           "Most in: " + _few([f"{c} ({n})" for c, n in top.items()], 4) + ".",
                           "Confirm them with the field team; they are flagged, not changed. They are listed "
                           "on the Outliers sheet of the Excel export."))
    real_violations = res.rule_violations[res.rule_violations["record"].notna()] if len(res.rule_violations) else []
    if len(real_violations):
        top = real_violations["rule"].value_counts()
        out.append(Finding("preview", "warning", f"{len(real_violations)} logic-check violation(s)",
                           "Most: " + _few([f"{r} ({n})" for r, n in top.items()], 4) + ".",
                           "Call back the enumerator for these records; see the Rule Violations sheet."))

    # Impossible ages and negative counts.
    for c in d.select_dtypes("number").columns:
        if c.startswith("_") or "__" in c:
            continue
        s = d[c].dropna()
        if _AGE.search(c):
            bad = s[(s < 0) | (s > 110)]
            if len(bad):
                out.append(Finding("preview", "problem", f"'{c}': impossible ages",
                                   f"{len(bad)} value(s) below 0 or above 110 (e.g. {_few(sorted(set(bad))[:3])}).",
                                   "Correct them, or add a constraint such as . >= 0 and . <= 110 in the form."))
        q = form.questions.get(c)
        if q is not None and q.qtype == "integer" and not _AGE.search(c) and (s < 0).any():
            out.append(Finding("preview", "warning", f"'{c}': negative values",
                               f"{int((s < 0).sum())} answer(s) are below zero.",
                               "If this is a count it cannot be negative: correct the entries or add a "
                               "constraint (. >= 0)."))

    # Missing answers: expected with skip logic, suspicious without.
    if len(res.missing):
        heavy = res.missing[res.missing["missing_pct"] >= 50]
        skipped = [r.column for r in heavy.itertuples() if form.questions.get(r.column) and form.questions[r.column].relevant]
        unexplained = [f"{r.column} ({r.missing_pct:g}%)" for r in heavy.itertuples()
                       if r.column not in skipped and not _OTHER.search(r.column)
                       and r.missing_pct < 100 and form.questions.get(r.column)]
        if unexplained:
            out.append(Finding("preview", "warning", f"{len(unexplained)} always-asked question(s) are often blank",
                               "More than half missing, with no skip logic in the form: " + _few(unexplained, 5) + ".",
                               "Check whether enumerators skipped them, or whether they were added in a later "
                               "form version."))
        if skipped:
            out.append(Finding("preview", "note", f"{len(skipped)} question(s) mostly blank because of skip logic",
                               _few(skipped, 6) + " are only asked in some cases.",
                               "Expected. Treat blanks there as 'not asked', not as missing answers."))

    # Interview length.
    if "duration_min" in d.columns:
        sub = d.drop_duplicates("_uuid") if "_uuid" in d.columns else d
        dur = sub["duration_min"].dropna()
        short = int((dur < short_minutes).sum())
        long = int((dur > long_minutes).sum())
        if long:
            out.append(Finding("preview", "warning", f"{long} submission(s) took over {long_minutes / 60:g} hours",
                               f"Median interview length is {dur.median():g} minutes.",
                               "Long times usually mean the form was left open or edited later, so interview "
                               "length is not a reliable quality measure for these."))
        if short:
            out.append(Finding("preview", "warning", f"{short} submission(s) under {short_minutes:g} minutes",
                               "Very short interviews can mean questions were rushed or skipped.",
                               "Check them with the enumerator summary and call back if needed."))

    # Enumerators.
    if res.enumerator_col and len(res.enumerators):
        e = res.enumerators
        if len(e) == 1:
            out.append(Finding("preview", "note", "All data came from one account",
                               f"'{res.enumerator_col}' has a single value ({e.iloc[0]['enumerator']}), so "
                               "enumerators cannot be compared.",
                               "Add an 'enumerator' question to the form to compare field staff."))
        else:
            rush = [c for c in e.columns if c.startswith("under_")]
            if rush:
                bad = e[(e[rush[0]] / e["submissions"]) > 0.25]
                if len(bad):
                    out.append(Finding("preview", "warning", "Enumerator(s) with many very short interviews",
                                       _few(bad["enumerator"].tolist()) + ": more than a quarter of their "
                                       "interviews are very short.",
                                       "Review their work and retrain if needed."))
    elif not res.enumerator_col:
        out.append(Finding("preview", "note", "No enumerator column found",
                           "Workload and quality cannot be compared per enumerator.",
                           "Add an 'enumerator' question, or type the column name in step 2."))

    # 'Other (specify)' answers.
    other = [(c, int(d[c].notna().sum())) for c in d.columns
             if _OTHER.search(c) and d[c].dtype == object and d[c].notna().any()]
    if other:
        out.append(Finding("preview", "note", "'Other (specify)' answers to review",
                           _few([f"{c} ({n})" for c, n in other], 5) + ".",
                           "Read them: some may belong to an existing option and can be recoded; frequent "
                           "ones may deserve a new option in the form."))

    # Personal data.
    personal = [c for c in d.columns
                if (_NAME.search(c) and not _NOT_PERSON_NAME.search(c)) or _PHONE.search(c) or
                _GPS.search(c)]
    if personal:
        out.append(Finding("preview", "warning", "The data contains personal information",
                           "Names, phone numbers or GPS: " + _few(personal, 6) + ".",
                           "Before sharing the file, choose 'Selected variables only' and untick these."))

    constant = [c for c in d.columns if not c.startswith("_") and "__" not in c
                and d[c].notna().sum() > 1 and d[c].nunique(dropna=True) == 1]
    if constant:
        out.append(Finding("preview", "note", f"{len(constant)} question(s) have the same answer everywhere",
                           _few(constant, 6) + ".",
                           "They add nothing to the analysis; you may leave them out."))
    return _sorted(out)


# --- step 4: the chosen file ----------------------------------------------------------------------

def check_export(res, fmt: str, keep: list[str] | None = None,
                 rename: dict[str, str] | None = None) -> list[Finding]:
    from .export import FORMATS, valid_names, variable_label  # late import: export imports pipeline

    out: list[Finding] = []
    cols = list(res.data.columns)
    chosen = [c for c in cols if keep is None or c in set(keep)]
    if keep is not None and not chosen:
        return [Finding("export", "problem", "No variables selected",
                        "Nothing would be exported.", "Tick at least one variable in step 3.")]
    if keep is not None and len(chosen) < len(cols):
        out.append(Finding("export", "note", f"{len(chosen)} of {len(cols)} variables selected",
                           "Only the ticked variables go into the file.", "Change the selection in step 3."))
    ids = [c for c in (res.id_col, "_uuid") if c in cols]
    if ids and not any(c in chosen for c in ids):
        out.append(Finding("export", "warning", "No row ID in the selection",
                           f"'{ids[0]}' is not ticked.",
                           "Without it, rows cannot be matched back to Kobo/ODK or to the Outliers and Rule "
                           "Violations sheets. Tick it unless you are sharing anonymised data."))
    personal = [c for c in chosen if (_NAME.search(c) and not _NOT_PERSON_NAME.search(c)) or _PHONE.search(c)]
    if personal:
        out.append(Finding("export", "warning", "Names or phone numbers will be in the file",
                           _few(personal, 5) + ".",
                           "Untick them in step 3 if the file will be shared."))

    f = FORMATS.get(fmt)
    if f is None:
        return _sorted(out)
    if not f.available:
        out.append(Finding("export", "problem", f"{f.label} is not available here",
                           f"It needs the '{f.needs}' package.", "Choose another format, or use the Windows app."))
    names = [(rename or {}).get(c, c) for c in chosen]
    if fmt in {"dta", "sav"}:
        fixed = [(a, b) for a, b in zip(names, valid_names(names, fmt)) if a != b]
        if fixed:
            out.append(Finding("export", "note", f"{len(fixed)} variable name(s) will be adjusted for "
                               f"{f.label.split(' (')[0]}",
                               _few([f"{a} → {b}" for a, b in fixed], 5) + ".",
                               "Rename them yourself in step 3 if you prefer other names."))
        if fmt == "dta":
            long_labels = [c for c in chosen if len(variable_label(res, c)) > 80]
            if long_labels:
                out.append(Finding("export", "note", f"{len(long_labels)} question text(s) shortened to 80 characters",
                                   "Stata variable labels hold at most 80 characters.",
                                   "Nothing to do; the full text stays in your XLSForm."))
    if fmt in {"csv", "html"}:
        out.append(Finding("export", "note", "This format keeps labels as plain text only",
                           "Codes and their labels are not stored side by side, and the Outliers / Rule "
                           "Violations / report are not included.",
                           "For analysis with value labels choose Stata, SPSS or R; for everything in one "
                           "file choose Excel."))
    if fmt == "xlsx" and len(res.data) > 1_048_575:
        out.append(Finding("export", "problem", "Too many rows for Excel",
                           f"{len(res.data):,} rows; Excel holds 1,048,575.", "Choose CSV, Stata, SPSS or R."))
    return _sorted(out)


def findings_table(findings: list[Finding]) -> pd.DataFrame:
    return pd.DataFrame([{"step": STEP_NAMES.get(f.step, f.step), "severity": f.severity, "finding": f.title,
                          "details": f.detail, "suggestion": f.suggestion} for f in findings],
                        columns=["step", "severity", "finding", "details", "suggestion"])
