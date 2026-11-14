"""Run every cleaning step in order and collect what each step found.

Workflow: read the export (with any repeat groups) -> remove duplicate
submissions -> reshape repeat groups to one long table -> drop system columns
-> tidy names -> recode missing codes -> fix types -> interview length ->
split multi-select answers -> flag outliers -> run consistency rules ->
summarise missing data and enumerators.

Answer codes are kept as codes here (so rules can use them); labels from the
XLSForm are applied when the single output file is written (see export.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from . import advisor, clean
from .errors import SurveyCleanError
from .tables import Survey, load_survey, reshape_long
from .xlsform import Form, load_form


@dataclass
class CleaningResult:
    raw_shape: tuple[int, int]
    data: pd.DataFrame
    form: Form = field(default_factory=Form)
    id_col: str = "_uuid"
    level: str = ""
    level_path: list[str] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)
    dropped_metadata: list[str] = field(default_factory=list)
    duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    recoded_missing: dict[str, int] = field(default_factory=dict)
    type_failures: dict[str, int] = field(default_factory=dict)
    multi_columns: list[str] = field(default_factory=list)
    outliers: pd.DataFrame = field(default_factory=pd.DataFrame)
    rule_violations: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing: pd.DataFrame = field(default_factory=pd.DataFrame)
    enumerator_col: str | None = None
    enumerators: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)
    findings: list = field(default_factory=list)  # advisor.Finding: checks & suggestions

    @property
    def submissions(self) -> int:
        return int(self.tables[0]["rows"]) - len(self.duplicates) if self.tables else len(self.data)


def read_export(path: str | Path) -> pd.DataFrame:
    """Read the main table of an export (kept for scripts that used it)."""
    s = load_survey(path)
    return s.tables[s.main].data.drop(columns=[c for c in s.tables[s.main].data.columns
                                               if c.startswith("__")])


def load_rules(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        raise SurveyCleanError(f"Rules file not found: {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SurveyCleanError(f"{path.name} is not a valid rules (YAML) file: {exc}") from exc
    rules = data.get("rules", []) if isinstance(data, dict) else []
    bad = [r for r in rules if not isinstance(r, dict) or "name" not in r or "check" not in r]
    if bad:
        raise SurveyCleanError(f"{path.name}: every rule needs a 'name' and a 'check'.")
    return rules


def load_form_checked(form) -> Form:
    if isinstance(form, Form):
        return form
    if not form:
        return Form()
    if not Path(form).exists():
        raise SurveyCleanError(f"Form file not found: {form}")
    try:
        return load_form(form)
    except ValueError as exc:
        raise SurveyCleanError(str(exc)) from exc
    except Exception as exc:  # unreadable Excel file
        raise SurveyCleanError(f"{Path(form).name} could not be read as an XLSForm ({exc}).") from exc


def inspect(data, form=None) -> Survey:
    """Read the export and report its tables (main + repeat groups) without cleaning.
    The XLSForm (optional) helps recognise repeat groups stored side by side."""
    return load_survey(data, load_form_checked(form))


def run(data, form=None, rules=None, id_col: str = "_uuid", outlier_k: float = 3.0,
        enumerator_col: str | None = None, short_minutes: float = 10.0,
        level: str | None = None) -> CleaningResult:
    """Clean a survey export end to end.

    `data`: a file path, several paths (ODK Central CSVs), a Survey, a DataFrame
    or a {table: DataFrame} dict. `level`: the table that defines one row of the
    output: the main table (one row per submission) or a repeat group (long
    format: one row per member / plot / ..., with the household answers repeated).
    Defaults to the first repeat group, or the main table when there is none.
    """
    form = load_form_checked(form)
    survey = data if isinstance(data, Survey) else load_survey(data, form)
    rules = load_rules(rules) if isinstance(rules, (str, Path)) else (rules or [])

    main = survey.tables[survey.main]
    res = CleaningResult(raw_shape=main.data.shape, data=main.data, form=form,
                         tables=survey.describe())
    res.raw_shape = (main.rows, main.data.shape[1] - sum(c.startswith("__") for c in main.data.columns))
    res.warnings.extend(survey.notes)
    # Checks & suggestions for steps 1 and 2 look at the files as received.
    chosen_level = level or survey.default_level()
    res.findings = advisor.check_upload(survey, form) + advisor.check_reshape(survey, chosen_level, form)

    # 1. Duplicate submissions are removed at the submission level, before the
    #    reshape, so the repeat-group rows of a duplicate go with it.
    data = main.data
    visible = data.drop(columns=[c for c in data.columns if c.startswith("__")])
    if id_col in data.columns:
        dupes = data[id_col].notna() & data[id_col].duplicated(keep="first")
    else:
        res.warnings.append(f"ID column '{id_col}' not found: duplicates are whole identical rows "
                            "and records are identified by row number.")
        dupes = visible.duplicated(keep="first")
    res.duplicates = visible.loc[dupes]
    survey.tables[survey.main].data = data.loc[~dupes].reset_index(drop=True)

    # 2. Reshape repeat groups to one long table.
    res.level = level or survey.default_level()
    res.level_path = survey.path_to(res.level) if res.level in survey.tables else [res.level]
    df, res.id_col, origins = reshape_long(survey, res.level, id_col=id_col)

    if form.questions:
        known = set(form.questions) | {"start", "end", "today", "deviceid", "username"}
        cols = {clean.short_name(c) for c in df.columns}
        if not known & cols:
            res.warnings.append("None of the form's questions match the data columns. "
                                "Is this the right XLSForm for this export?")

    # 3. Cleaning steps.
    keep = {enumerator_col} if enumerator_col else set()
    if not enumerator_col and "_submitted_by" in df.columns and not any(
            clean.short_name(c) in clean.ENUMERATOR_CANDIDATES for c in df.columns if not c.startswith("_")):
        keep.add("_submitted_by")  # the only record of who collected the data
    meta = [c for c in clean.DEFAULT_METADATA if c not in keep]
    df, res.dropped_metadata = clean.drop_metadata(df, meta)
    df, res.renamed = clean.clean_column_names(df)

    # In long data the household answers repeat on every member row. Count and
    # check them once per submission, so a large household does not count twice.
    clean_origin = {res.renamed.get(raw, raw): table for raw, table in origins.items()}

    def submission_level(col: str) -> bool:
        base = col.split("__")[0]
        return clean_origin.get(col, clean_origin.get(base, survey.main)) == survey.main

    long = res.id_col != id_col and id_col in df.columns

    def per_submission(before: pd.DataFrame, after: pd.DataFrame, counts: dict[str, int]) -> dict[str, int]:
        if not long:
            return counts
        out = {}
        for col, n in counts.items():
            if submission_level(col):
                changed = before[col].notna() & after[col].isna()
                n = int(after.loc[changed, id_col].nunique())
            if n:
                out[col] = n
        return out

    before = df
    df, recoded = clean.recode_missing(df)
    res.recoded_missing = per_submission(before, df, recoded)
    before = df
    df, failures = clean.coerce_types(df, form)
    res.type_failures = per_submission(before, df, failures)
    df = clean.add_duration(df, form=form)
    df, res.multi_columns = clean.split_select_multiple(df, form)

    # Rules about a repeat group that is not part of this output (e.g. member
    # ages when the output has one row per household) cannot run here: skip
    # them with a note instead of reporting a broken rule.
    off_path = {name for name, q in form.questions.items()
                if q.repeat and q.repeat not in res.level_path and name not in df.columns}
    runnable = []
    for r in rules:
        missing_cols = sorted(set(re.findall(r"[A-Za-z_]\w*", str(r["check"]))) & off_path)
        if missing_cols:
            res.warnings.append(f"Rule '{r['name']}' was not run: it uses repeat-group answers "
                                f"({', '.join(missing_cols)}). Choose that repeat group as the row "
                                "level to check it.")
        else:
            runnable.append(r)
    rules = runnable

    if long:
        per_sub = df.drop_duplicates(id_col)
        numeric = clean.outlier_columns(df)
        res.outliers = pd.concat([
            clean.flag_outliers(per_sub, [c for c in numeric if submission_level(c)], outlier_k, id_col),
            clean.flag_outliers(df, [c for c in numeric if not submission_level(c)], outlier_k, res.id_col),
        ], ignore_index=True)
        sub_rules = [r for r in rules
                     if all(submission_level(c) for c in clean.rule_columns(df, r["check"]))]
        child_rules = [r for r in rules if r not in sub_rules]
        res.rule_violations = pd.concat([
            clean.check_rules(per_sub, sub_rules, id_col=id_col),
            clean.check_rules(df, child_rules, id_col=res.id_col),
        ], ignore_index=True)
        sub_cols = [c for c in df.columns if submission_level(c)]
        res.missing = (pd.concat([clean.missingness(per_sub[sub_cols]),
                                  clean.missingness(df[[c for c in df.columns if c not in sub_cols]])])
                       .sort_values("missing_pct", ascending=False, kind="stable").reset_index(drop=True))
    else:
        res.outliers = clean.flag_outliers(df, k=outlier_k, id_col=res.id_col)
        res.rule_violations = clean.check_rules(df, rules, id_col=res.id_col)
        res.missing = clean.missingness(df)

    res.enumerator_col = clean.find_enumerator_column(df, enumerator_col)
    if enumerator_col and res.enumerator_col is None:
        res.warnings.append(f"Enumerator column '{enumerator_col}' not found.")
    if res.enumerator_col:
        res.enumerators = clean.enumerator_summary(
            df, res.enumerator_col, res.outliers, res.rule_violations, res.duplicates,
            id_col=res.id_col, short_minutes=short_minutes)
    res.data = df
    res.findings += advisor.check_cleaned(res, short_minutes=short_minutes)
    return res
