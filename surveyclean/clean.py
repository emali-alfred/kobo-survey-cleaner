"""Cleaning steps for KoboToolbox / ODK survey exports.

Cleaning steps return a new DataFrame (the input is never modified) together
with what they changed; checking steps return a table of findings. Everything
found is listed in the data quality report.
"""

from __future__ import annotations

import re

import pandas as pd

from .xlsform import Form

# Kobo system columns that are rarely needed for analysis.
DEFAULT_METADATA = [
    "_id", "_validation_status", "_notes", "_status", "_submitted_by",
    "__version__", "_tags", "_index", "_attachments", "_geolocation",
    "formhub/uuid", "meta/instanceID", "meta/rootUuid", "_xform_id_string",
]

# Codes commonly used in surveys for "don't know", "refused", "not applicable".
DEFAULT_MISSING_CODES = [-99, -98, -88, -77, -999, "dk", "don't know", "refused", "n/a", "na", ""]


def drop_metadata(df: pd.DataFrame, columns: list[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Drop Kobo system columns. Returns the new frame and the columns removed."""
    targets = columns if columns is not None else DEFAULT_METADATA
    removed = [c for c in df.columns if c in targets]
    return df.drop(columns=removed), removed


def clean_column_names(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Strip group prefixes ("hh_info/livestock/cattle" -> "cattle") and make
    names snake_case. Kobo's own underscore columns (e.g. "_uuid") are kept.
    If two columns end up with the same name, the full path is used instead.
    """

    def short(name: str) -> str:
        if name.startswith("_"):
            return name
        return name.split("/")[-1]

    def snake(name: str) -> str:
        if name.startswith("_"):
            return name
        name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
        return name or "unnamed"

    candidates = [snake(short(c)) for c in df.columns]
    counts = pd.Series(candidates).value_counts()
    mapping: dict[str, str] = {}
    for original, cand in zip(df.columns, candidates):
        mapping[original] = snake(original) if counts[cand] > 1 else cand
    return df.rename(columns=mapping), {k: v for k, v in mapping.items() if k != v}


def remove_duplicates(df: pd.DataFrame, key: str = "_uuid") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove repeated submissions (same key). Keeps the first; returns the dropped rows."""
    if key not in df.columns:
        dupes_mask = df.duplicated(keep="first")
    else:
        dupes_mask = df.duplicated(subset=[key], keep="first")
    return df.loc[~dupes_mask].reset_index(drop=True), df.loc[dupes_mask]


def recode_missing(df: pd.DataFrame, codes: list | None = None,
                   columns: list[str] | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Replace special missing codes (-99, "don't know", ...) with real missing values.
    Returns the new frame and how many values were recoded per column."""
    codes = DEFAULT_MISSING_CODES if codes is None else codes
    cols = columns or [c for c in df.columns if not c.startswith("_")]
    out = df.copy()
    counts: dict[str, int] = {}
    code_strs = {str(c).strip().lower() for c in codes}
    for col in cols:
        s = out[col]
        as_str = s.astype("string").str.strip().str.lower()
        mask = as_str.isin(code_strs) & s.notna()
        n = int(mask.sum())
        if n:
            out[col] = s.mask(mask)
            counts[col] = n
    return out, counts


def coerce_types(df: pd.DataFrame, form: Form) -> tuple[pd.DataFrame, dict[str, int]]:
    """Convert integer/decimal questions to numbers and date questions to dates.
    Returns how many values in each column could not be converted."""
    out = df.copy()
    failures: dict[str, int] = {}
    for q in form.questions.values():
        if q.name not in out.columns:
            continue
        before = out[q.name].notna().sum()
        if q.qtype in {"integer", "decimal", "range"}:
            out[q.name] = pd.to_numeric(out[q.name], errors="coerce")
        elif q.qtype in {"date", "datetime", "start", "end", "today"}:
            out[q.name] = pd.to_datetime(out[q.name], errors="coerce", utc=q.qtype != "date")
        else:
            continue
        lost = int(before - out[q.name].notna().sum())
        if lost:
            failures[q.name] = lost
    return out, failures


def split_select_multiple(df: pd.DataFrame, form: Form) -> tuple[pd.DataFrame, list[str]]:
    """Turn space-separated select_multiple answers ("maize beans") into 0/1 columns
    (crops__maize, crops__beans). Keeps the original column."""
    out = df.copy()
    created: list[str] = []
    for q in form.of_type("select_multiple"):
        if q.name not in out.columns:
            continue
        options = list(form.choice_labels(q.name)) or sorted(
            {v for cell in out[q.name].dropna() for v in str(cell).split()}
        )
        answered = out[q.name].notna()
        tokens = out[q.name].fillna("").astype(str).str.split()
        for opt in options:
            col = f"{q.name}__{opt}"
            out[col] = tokens.apply(lambda vals, o=opt: int(o in vals)).where(answered)
            out[col] = out[col].astype("Int64")
            created.append(col)
    return out, created


def apply_labels(df: pd.DataFrame, form: Form, suffix: str = "_label") -> tuple[pd.DataFrame, list[str]]:
    """Add readable label columns for select_one questions ("1" -> "Male")."""
    out = df.copy()
    created: list[str] = []
    for q in form.of_type("select_one"):
        if q.name not in out.columns:
            continue
        labels = form.choice_labels(q.name)
        if not labels:
            continue
        col = f"{q.name}{suffix}"
        out[col] = out[q.name].astype("string").str.strip().map(labels)
        created.append(col)
    return out, created


def _fmt(x: float) -> str:
    if float(x).is_integer() or abs(x) >= 100:
        return f"{x:,.0f}"
    return f"{x:.3g}"


def flag_outliers(df: pd.DataFrame, columns: list[str] | None = None, k: float = 3.0,
                  id_col: str = "_uuid") -> pd.DataFrame:
    """Flag extreme numeric values using the IQR rule (outside Q1 - k*IQR, Q3 + k*IQR).
    Values are flagged, not removed: a 300-cow herd may be real and needs a human check."""
    cols = columns or [c for c in df.select_dtypes("number").columns
                       if not c.startswith("_") and "__" not in c]
    rows = []
    for col in cols:
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() < 5:
            continue
        q1, q3 = s.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            continue
        low, high = q1 - k * iqr, q3 + k * iqr
        mask = (s < low) | (s > high)
        for idx in s[mask].index:
            rows.append({
                "record": df.at[idx, id_col] if id_col in df.columns else idx,
                "column": col,
                "value": _fmt(s[idx]),
                "expected_range": f"{_fmt(max(low, s.min()))} to {_fmt(high)}",
            })
    return pd.DataFrame(rows, columns=["record", "column", "value", "expected_range"])


def check_rules(df: pd.DataFrame, rules: list[dict], id_col: str = "_uuid") -> pd.DataFrame:
    """Run consistency checks. Each rule is {"name": ..., "check": <pandas expression
    that must be True>}. Rows where the check is False are returned.
    Rows where the check cannot be evaluated (missing values) are not flagged."""
    rows = []
    for rule in rules:
        name, expr = rule["name"], rule["check"]
        try:
            ok = df.eval(expr)
        except Exception as exc:  # bad rule: report it rather than crash
            rows.append({"record": None, "rule": name, "detail": f"Rule could not run: {exc}"})
            continue
        ok = pd.Series(ok, index=df.index).astype("boolean")
        # Only judge records where every column the rule uses is answered.
        used = [c for c in df.columns if re.search(rf"(?<![\w.]){re.escape(c)}(?!\w)", expr)]
        answered = df[used].notna().all(axis=1) if used else pd.Series(True, index=df.index)
        failed = ok.eq(False).fillna(False).astype(bool) & answered
        for idx in df.index[failed]:
            rows.append({
                "record": df.at[idx, id_col] if id_col in df.columns else idx,
                "rule": name,
                "detail": rule.get("message", expr),
            })
    return pd.DataFrame(rows, columns=["record", "rule", "detail"])


def missingness(df: pd.DataFrame) -> pd.DataFrame:
    """Share of missing values per column, highest first."""
    cols = [c for c in df.columns if not c.startswith("_") and "__" not in c]
    pct = df[cols].isna().mean().mul(100).round(1)
    return (pct[pct > 0].sort_values(ascending=False)
            .rename_axis("column").reset_index(name="missing_pct"))
