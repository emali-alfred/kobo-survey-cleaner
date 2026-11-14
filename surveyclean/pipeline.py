"""Run every cleaning step in order and collect what each step found."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from . import clean
from .xlsform import Form, load_form


class SurveyCleanError(Exception):
    """A problem with the user's input files, explained in plain language."""


@dataclass
class CleaningResult:
    raw_shape: tuple[int, int]
    data: pd.DataFrame
    renamed: dict[str, str] = field(default_factory=dict)
    dropped_metadata: list[str] = field(default_factory=list)
    duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    recoded_missing: dict[str, int] = field(default_factory=dict)
    type_failures: dict[str, int] = field(default_factory=dict)
    multi_columns: list[str] = field(default_factory=list)
    label_columns: list[str] = field(default_factory=list)
    outliers: pd.DataFrame = field(default_factory=pd.DataFrame)
    rule_violations: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing: pd.DataFrame = field(default_factory=pd.DataFrame)
    enumerator_col: str | None = None
    enumerators: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)


def read_export(path: str | Path) -> pd.DataFrame:
    """Read a Kobo/ODK export. CSV separator (',' or ';') is detected automatically.
    For Excel exports the first sheet is read (repeat groups are on other sheets)."""
    path = Path(path)
    if not path.exists():
        raise SurveyCleanError(f"Data file not found: {path}")
    suffix = path.suffix.lower()
    try:
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            return pd.read_excel(path, dtype=str, sheet_name=0)
        try:
            return pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:  # files re-saved in Excel on Windows
            return pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="cp1252")
    except ImportError as exc:
        raise SurveyCleanError(f"Cannot read {path.name}: {exc}. Save it as .xlsx or .csv.") from exc
    except pd.errors.EmptyDataError as exc:
        raise SurveyCleanError(f"{path.name} is empty.") from exc


def load_rules(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        raise SurveyCleanError(f"Rules file not found: {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise SurveyCleanError(f"{path.name} is not valid YAML: {exc}") from exc
    rules = data.get("rules", []) if isinstance(data, dict) else []
    bad = [r for r in rules if not isinstance(r, dict) or "name" not in r or "check" not in r]
    if bad:
        raise SurveyCleanError(f"{path.name}: every rule needs a 'name' and a 'check'.")
    return rules


def run(data: pd.DataFrame | str | Path, form: Form | str | Path | None = None,
        rules: list[dict] | str | Path | None = None, id_col: str = "_uuid",
        outlier_k: float = 3.0, enumerator_col: str | None = None,
        short_minutes: float = 10.0) -> CleaningResult:
    """Clean a survey export end to end.

    Steps: drop system columns -> tidy names -> remove duplicate submissions ->
    recode missing codes -> fix types -> interview duration -> split multi-select
    answers -> add labels -> flag outliers -> run consistency rules -> summarise
    missing data -> enumerator summary.
    """
    df = read_export(data) if isinstance(data, (str, Path)) else data.copy()
    if isinstance(form, (str, Path)):
        if not Path(form).exists():
            raise SurveyCleanError(f"Form file not found: {form}")
        form = load_form(form)
    form = form or Form()
    rules = load_rules(rules) if isinstance(rules, (str, Path)) else (rules or [])

    res = CleaningResult(raw_shape=df.shape, data=df)
    keep = {enumerator_col} if enumerator_col else set()
    meta = [c for c in clean.DEFAULT_METADATA if c not in keep]
    df, res.dropped_metadata = clean.drop_metadata(df, meta)
    df, res.renamed = clean.clean_column_names(df)
    if id_col not in df.columns:
        res.warnings.append(f"ID column '{id_col}' not found: duplicates are whole identical rows "
                            "and records are identified by row number.")
    if form.questions:
        missing_q = [q for q in form.questions if q not in df.columns
                     and q not in {"start", "end", "today", "deviceid", "username"}]
        if len(missing_q) == len(form.questions):
            res.warnings.append("None of the form's questions match the data columns. "
                                "Is this the right form for this export?")
    df, res.duplicates = clean.remove_duplicates(df, key=id_col)
    df, res.recoded_missing = clean.recode_missing(df)
    df, res.type_failures = clean.coerce_types(df, form)
    df = clean.add_duration(df)
    df, res.multi_columns = clean.split_select_multiple(df, form)
    df, res.label_columns = clean.apply_labels(df, form)
    res.outliers = clean.flag_outliers(df, k=outlier_k, id_col=id_col)
    res.rule_violations = clean.check_rules(df, rules, id_col=id_col)
    res.missing = clean.missingness(df)

    res.enumerator_col = clean.find_enumerator_column(df, enumerator_col)
    if enumerator_col and res.enumerator_col is None:
        res.warnings.append(f"Enumerator column '{enumerator_col}' not found.")
    if res.enumerator_col:
        res.enumerators = clean.enumerator_summary(
            df, res.enumerator_col, res.outliers, res.rule_violations, res.duplicates,
            id_col=id_col, short_minutes=short_minutes)
    res.data = df
    return res
