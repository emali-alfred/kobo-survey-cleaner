"""Run every cleaning step in order and collect what each step found."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from . import clean
from .xlsform import Form, load_form


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


def read_export(path: str | Path) -> pd.DataFrame:
    """Read a Kobo/ODK export. CSV separator (',' or ';') is detected automatically."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str)
    return pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="utf-8-sig")


def load_rules(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("rules", [])


def run(data: pd.DataFrame | str | Path, form: Form | str | Path | None = None,
        rules: list[dict] | str | Path | None = None, id_col: str = "_uuid",
        outlier_k: float = 3.0) -> CleaningResult:
    """Clean a survey export end to end.

    Steps: drop system columns -> tidy names -> remove duplicate submissions ->
    recode missing codes -> fix types -> split multi-select answers -> add labels ->
    flag outliers -> run consistency rules -> summarise missing data.
    """
    df = read_export(data) if isinstance(data, (str, Path)) else data.copy()
    form = load_form(form) if isinstance(form, (str, Path)) else (form or Form())
    rules = load_rules(rules) if isinstance(rules, (str, Path)) else (rules or [])

    res = CleaningResult(raw_shape=df.shape, data=df)
    df, res.dropped_metadata = clean.drop_metadata(df)
    df, res.renamed = clean.clean_column_names(df)
    df, res.duplicates = clean.remove_duplicates(df, key=id_col)
    df, res.recoded_missing = clean.recode_missing(df)
    df, res.type_failures = clean.coerce_types(df, form)
    df, res.multi_columns = clean.split_select_multiple(df, form)
    df, res.label_columns = clean.apply_labels(df, form)
    res.outliers = clean.flag_outliers(df, k=outlier_k, id_col=id_col)
    res.rule_violations = clean.check_rules(df, rules, id_col=id_col)
    res.missing = clean.missingness(df)
    res.data = df
    return res
