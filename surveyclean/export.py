"""Write the cleaned survey as ONE file, in the format the user chooses.

* Excel workbook (.xlsx): four sheets: the clean data (named after the file),
  Outliers, Rule Violations and the Data Quality Report.
* CSV, R (.rds / .RData), Stata (.dta), SPSS (.sav), HTML: the clean data only.

Answer codes are replaced with the labels from the XLSForm. Stata and SPSS keep
the numeric codes and attach the labels as value labels (and question texts as
variable labels), R gets factors, the other formats get the label text.

Missing values follow each format's own convention: empty cells in Excel, CSV
and HTML; NA in R; "." (system missing) in Stata and SPSS numeric variables and
empty strings in their text variables.
"""

from __future__ import annotations

import html
import importlib.util
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .clean import label_codes, label_multi_codes
from .errors import SurveyCleanError
from .pipeline import CleaningResult
from .xlsform import code_key

NAME_REQUIRED = "Error: Output file name is required before export."


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    ext: str
    needs: str | None = None  # Python package that writes it

    @property
    def available(self) -> bool:
        return self.needs is None or importlib.util.find_spec(self.needs) is not None


FORMATS: dict[str, Format] = {f.key: f for f in [
    Format("xlsx", "Excel Workbook (.xlsx)", ".xlsx", "openpyxl"),
    Format("csv", "CSV (.csv)", ".csv"),
    Format("rds", "R data file (.rds)", ".rds", "pyreadr"),
    Format("RData", "R workspace (.RData)", ".RData", "pyreadr"),
    Format("dta", "Stata (.dta)", ".dta"),
    Format("sav", "SPSS (.sav)", ".sav", "pyreadstat"),
    Format("html", "HTML table (.html)", ".html"),
]}

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_ALL_EXTS = {f.ext.lower() for f in FORMATS.values()}


def get_format(fmt: str) -> Format:
    key = {k.lower(): k for k in FORMATS}.get(str(fmt).lower().lstrip("."))
    if key is None:
        raise SurveyCleanError(f"Unknown format '{fmt}'. Choose one of: {', '.join(FORMATS)}.")
    f = FORMATS[key]
    if not f.available:
        raise SurveyCleanError(f"{f.label} export needs the '{f.needs}' package, which is not "
                               "installed here. Choose another format.")
    return f


def clean_filename(name: str | None) -> str:
    """Strip characters Windows does not allow in file names (\\ / : * ? " < > |).
    Raises the "name is required" error when nothing usable is left."""
    text = _ILLEGAL.sub("", str(name or "")).strip().rstrip(". ").strip()
    for ext in _ALL_EXTS:  # "report.xlsx" -> "report"
        if text.lower().endswith(ext):
            text = text[: -len(ext)].rstrip(". ").strip()
            break
    if not text:
        raise SurveyCleanError(NAME_REQUIRED)
    if text.split(".")[0].upper() in _RESERVED:
        text = f"{text}_"
    return text[:150]


def output_path(folder: str | Path, name: str, fmt: str) -> Path:
    return Path(folder) / f"{clean_filename(name)}{get_format(fmt).ext}"


# --- variables: labels, renames, valid names -------------------------------------

SPECIAL_LABELS = {
    "_record": "Row ID (submission / repeat group record)",
    "_uuid": "Submission ID",
    "_submission_time": "Time the submission reached the server",
    "duration_min": "Interview length (minutes)",
}


def variable_label(res: CleaningResult, column: str) -> str:
    label = res.form.label(column) if res.form else None
    if label:
        return str(label)
    if column in SPECIAL_LABELS:
        return SPECIAL_LABELS[column]
    if column.startswith("n_"):
        return f"Number of '{column[2:]}' records"
    return ""


def variable_table(res: CleaningResult) -> pd.DataFrame:
    """Columns of the clean data with their question text, for the rename screen."""
    return pd.DataFrame({
        "original": list(res.data.columns),
        "label": [variable_label(res, c) for c in res.data.columns],
    })


def check_renames(columns: list[str], rename: dict[str, str] | None) -> dict[str, str]:
    """Keep only real changes; refuse empty or duplicate names."""
    rename = {k: str(v).strip() for k, v in (rename or {}).items()
              if k in columns and v is not None and str(v).strip() and str(v).strip() != k}
    final = [rename.get(c, c) for c in columns]
    seen, dupes = set(), set()
    for n in final:
        (dupes if n in seen else seen).add(n)
    if dupes:
        raise SurveyCleanError("Two variables would have the same name: " + ", ".join(sorted(dupes))
                               + ". Choose different new names.")
    return rename


_SPSS_RESERVED = {"ALL", "AND", "BY", "EQ", "GE", "GT", "LE", "LT", "NE", "NOT", "OR", "TO", "WITH"}
try:  # Stata's reserved words, as pandas knows them
    from pandas.io.stata import StataWriter as _SW
    _STATA_RESERVED = {w.lower() for w in _SW.RESERVED_WORDS}
except (ImportError, AttributeError):
    _STATA_RESERVED = {"aggregate", "array", "boolean", "break", "byte", "case", "catch", "class",
                       "colvector", "complex", "const", "continue", "default", "delegate", "delete",
                       "do", "double", "else", "eltypedef", "end", "enum", "explicit", "export",
                       "external", "float", "for", "friend", "function", "global", "goto", "if",
                       "inline", "int", "local", "long", "null", "pragma", "protected", "quad",
                       "rowvector", "short", "typedef", "typename", "virtual", "_all", "_n", "_skip",
                       "_b", "_pi", "str#", "in", "_pred", "strl", "_coef", "_rc", "using", "_cons",
                       "_se", "with", "_n"}


def valid_names(names: list[str], fmt: str) -> list[str]:
    """Make variable names legal for Stata (32 chars, letters/digits/_) and
    SPSS (64 chars, starts with a letter). Other formats keep names as they are."""
    if fmt not in {"dta", "sav"}:
        return list(names)
    limit = 32 if fmt == "dta" else 64
    out, used = [], set()
    for name in names:
        n = re.sub(r"[^0-9A-Za-z_]", "_", name)
        if fmt == "dta" and (not n or n[0].isdigit()):
            n = "v" + n
        if fmt == "dta" and n.lower() in _STATA_RESERVED:
            n += "_"
        if fmt == "sav":
            if not n or not n[0].isalpha():
                n = "v" + n.lstrip("_")
            if n.upper() in _SPSS_RESERVED:
                n += "_"
        n = n[:limit] or "v"
        base, i = n, 2
        while n.lower() in used:
            suffix = f"_{i}"
            n = base[: limit - len(suffix)] + suffix
            i += 1
        used.add(n.lower())
        out.append(n)
    return out


# --- preparing the data for one format --------------------------------------------

@dataclass
class Prepared:
    data: pd.DataFrame
    variable_labels: dict[str, str] = field(default_factory=dict)
    value_labels: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _numeric_codes(labels: dict[str, str]) -> bool:
    return bool(labels) and all(re.fullmatch(r"-?\d+", k) for k in labels)


def _apply_labels(df: pd.DataFrame, res: CleaningResult, fmt: str, prep: Prepared) -> pd.DataFrame:
    form = res.form
    for q in form.of_type("select_one"):
        if q.name not in df.columns:
            continue
        labels = form.choice_labels(q.name)
        if not labels:
            continue
        s = df[q.name]
        keys = s.map(lambda v: code_key(v) if pd.notna(v) else None)
        unknown = sorted({k for k in keys.dropna() if k not in labels})
        if fmt in {"dta", "sav"}:
            if _numeric_codes(labels) and not unknown:
                df[q.name] = pd.to_numeric(keys, errors="coerce")
                prep.value_labels[q.name] = {int(k): v for k, v in labels.items()}
                continue
            if not unknown:  # text codes: number them in choice order
                order = {k: i + 1 for i, k in enumerate(labels)}
                df[q.name] = keys.map(order).astype("float64")
                prep.value_labels[q.name] = {order[k]: v for k, v in labels.items()}
                continue
            df[q.name] = label_codes(s, labels)  # unexpected codes: keep text so nothing is lost
            prep.notes.append(f"{q.name}: codes {', '.join(unknown[:5])} are not in the XLSForm "
                              "choices, so it is written as text.")
        elif fmt in {"rds", "RData"}:
            cats = list(dict.fromkeys(list(labels.values()) + [labels.get(k, k) for k in unknown]))
            df[q.name] = pd.Categorical(label_codes(s, labels).astype(object).where(s.notna(), None),
                                        categories=cats)
        else:
            df[q.name] = label_codes(s, labels)
    for q in form.of_type("select_multiple"):
        if q.name in df.columns and form.choice_labels(q.name):
            df[q.name] = label_multi_codes(df[q.name], form.choice_labels(q.name))
        if fmt in {"dta", "sav"}:
            for c in res.multi_columns:
                if c.startswith(f"{q.name}__") and c in df.columns:
                    prep.value_labels[c] = {0: "No", 1: "Yes"}
    return df


def _plain_types(df: pd.DataFrame, fmt: str) -> pd.DataFrame:
    """Convert pandas-only types to what each file format can store."""
    for c in df.columns:
        s = df[c]
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            if fmt in {"csv", "html"}:
                df[c] = s.map(lambda v: v.isoformat() if pd.notna(v) else None)
            else:  # local clock time; these formats have no time zones
                df[c] = s.dt.tz_localize(None)
        elif isinstance(s.dtype, pd.CategoricalDtype):
            continue
        elif pd.api.types.is_bool_dtype(s.dtype):
            df[c] = s.astype("float64") if fmt in {"dta", "sav", "rds", "RData"} else s
        elif pd.api.types.is_integer_dtype(s.dtype) and s.dtype != np.int64 and fmt in {"dta", "sav", "rds", "RData"}:
            df[c] = s.astype("float64")  # nullable integers: missing becomes a real missing value
        elif pd.api.types.is_float_dtype(s.dtype) and fmt in {"csv", "xlsx", "html"}:
            # Whole numbers with gaps are floats in pandas; write 44, not 44.0.
            whole = s.dropna()
            if not whole.empty and (whole == whole.round()).all() and whole.abs().max() < 2**53:
                df[c] = s.astype("Int64")
        elif pd.api.types.is_numeric_dtype(s.dtype):
            continue
        elif pd.api.types.is_datetime64_any_dtype(s.dtype):
            if fmt in {"csv", "html"}:
                df[c] = s.map(lambda v: v.isoformat() if pd.notna(v) else None)
        else:  # text
            text = s.astype(object).where(s.notna(), None).map(lambda v: v if v is None else str(v))
            if fmt in {"dta", "sav"}:
                text = text.where(text.notna(), "")  # Stata/SPSS text missing = empty string
            df[c] = text
    return df


def selected_columns(res: CleaningResult, keep: list[str] | None) -> list[str]:
    """The variables to export, in data order. `keep=None` means all of them."""
    if keep is None:
        return list(res.data.columns)
    wanted = set(keep)
    chosen = [c for c in res.data.columns if c in wanted]
    if not chosen:
        raise SurveyCleanError("Choose at least one variable to export.")
    return chosen


def prepare(res: CleaningResult, fmt: str, rename: dict[str, str] | None = None,
            use_labels: bool = True, keep: list[str] | None = None) -> Prepared:
    """The data as it will be written: selected variables, labels, renames, types."""
    fmt = get_format(fmt).key
    df = res.data[selected_columns(res, keep)].copy()
    prep = Prepared(df)
    if use_labels and res.form.choices:
        df = _apply_labels(df, res, fmt, prep)
    df = _plain_types(df, fmt)
    prep.variable_labels = {c: variable_label(res, c) for c in df.columns}

    rename = check_renames(list(df.columns), rename)
    wanted = [rename.get(c, c) for c in df.columns]
    final = valid_names(wanted, fmt)
    changed = [(w, f) for w, f in zip(wanted, final) if w != f]
    if changed:
        shown = ", ".join(f"{w} → {f}" for w, f in changed[:6])
        more = f" and {len(changed) - 6} more" if len(changed) > 6 else ""
        prep.notes.append(f"Renamed to valid {get_format(fmt).label.split(' (')[0]} variable names: {shown}{more}.")
    mapping = dict(zip(df.columns, final))
    prep.data = df.rename(columns=mapping)
    prep.variable_labels = {mapping[k]: v for k, v in prep.variable_labels.items() if v}
    prep.value_labels = {mapping[k]: v for k, v in prep.value_labels.items()}
    return prep


# --- writers ------------------------------------------------------------------------

def _sheet_name(name: str) -> str:
    return re.sub(r"[\[\]:*?/\\]", "", name).strip("' ")[:31] or "Clean Data"


def _write_xlsx(path: Path, prep: Prepared, res: CleaningResult, data_sheet: str, title: str,
                findings: list | None = None) -> None:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from .report import quality_report_rows

    data_sheet = _sheet_name(data_sheet)
    other = {"Outliers", "Rule Violations", "Data Quality Report"}
    if data_sheet in other:
        data_sheet = f"{data_sheet} data"[:31]
    head = Font(bold=True)
    fill = PatternFill("solid", fgColor="E3F4EE")
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        tables = [(data_sheet, prep.data), ("Outliers", res.outliers), ("Rule Violations", res.rule_violations)]
        for name, df in tables:
            if df.empty:  # keep the headers, say so instead of an empty sheet
                cols = list(df.columns) or ["note"]
                df = pd.DataFrame([["None found."] + [None] * (len(cols) - 1)], columns=cols)
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font, cell.fill = head, fill
            for i, col in enumerate(df.columns, start=1):
                sample = [str(col)] + [str(v) for v in df[col].head(200) if pd.notna(v)]
                ws.column_dimensions[get_column_letter(i)].width = min(max(map(len, sample), default=8) + 2, 50)

        ws = xw.book.create_sheet("Data Quality Report")
        ws.column_dimensions["A"].width = 46
        for col in "BCDEFGHIJ":
            ws.column_dimensions[col].width = 18
        for kind, values in quality_report_rows(res, title, prep.notes, findings):
            ws.append(values)
            row = ws[ws.max_row]
            if kind == "title":
                row[0].font = Font(bold=True, size=14)
            elif kind == "heading":
                row[0].font = Font(bold=True, size=12)
            elif kind == "header":
                for cell in row:
                    if cell.value is not None:
                        cell.font, cell.fill = head, fill


def _write_html(path: Path, prep: Prepared, title: str) -> None:
    df = prep.data
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = "\n".join(
        "<tr>" + "".join(f"<td>{'' if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA else html.escape(str(v))}</td>"
                         for v in r) + "</tr>"
        for r in df.itertuples(index=False))
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#fff;--fg:#16232b;--line:#dfe7e5;--head:#e3f4ee}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1518;--fg:#e5eef0;--line:#26333a;--head:#143229}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,"Segoe UI",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0 0 12px;opacity:.75}}
.wrap{{overflow:auto;border:1px solid var(--line);border-radius:8px;max-height:85vh}}
table{{border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:left}}
th{{background:var(--head);position:sticky;top:0}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p>{len(df):,} rows × {len(df.columns)} variables · generated {datetime.now():%Y-%m-%d %H:%M}</p>
<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>
{rows}
</tbody></table></div></body></html>
""", encoding="utf-8")


def _write_dta(path: Path, prep: Prepared) -> None:
    df = prep.data
    strl = [c for c in df.columns if df[c].dtype == object and df[c].map(lambda v: len(str(v)) if v else 0).max() > 2000]
    labels = {k: v[:80] for k, v in prep.variable_labels.items()}
    value_labels = {k: {int(code): str(lab)[:32000] for code, lab in v.items()} for k, v in prep.value_labels.items()}
    df.to_stata(path, write_index=False, version=118, variable_labels=labels,
                value_labels=value_labels or None, convert_strl=strl)


def _write_sav(path: Path, prep: Prepared) -> None:
    import pyreadstat

    df = prep.data
    pyreadstat.write_sav(df, str(path),
                         column_labels=[prep.variable_labels.get(c) or None for c in df.columns],
                         variable_value_labels={k: {float(c): lab for c, lab in v.items()}
                                                for k, v in prep.value_labels.items()})


def _r_object_name(name: str) -> str:
    n = re.sub(r"[^0-9A-Za-z_.]", "_", name)
    return n if n and (n[0].isalpha() or n[0] == ".") else f"survey_{n}"


def export_file(res: CleaningResult, folder: str | Path, name: str, fmt: str,
                rename: dict[str, str] | None = None, use_labels: bool = True,
                title: str | None = None, keep: list[str] | None = None) -> tuple[Path, list[str]]:
    """Write the single output file. Returns its path and any notes for the user.
    `keep`: the variables to export (None = all)."""
    f = get_format(fmt)
    base = clean_filename(name)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{base}{f.ext}"
    prep = prepare(res, f.key, rename, use_labels, keep)
    title = title or base
    try:
        if f.key == "xlsx":
            from .advisor import check_export
            _write_xlsx(path, prep, res, base, title, res.findings + check_export(res, f.key, keep, rename))
        elif f.key == "csv":
            prep.data.to_csv(path, index=False, encoding="utf-8-sig", na_rep="")
        elif f.key == "html":
            _write_html(path, prep, title)
        elif f.key == "dta":
            _write_dta(path, prep)
        elif f.key == "sav":
            _write_sav(path, prep)
        elif f.key == "rds":
            import pyreadr
            pyreadr.write_rds(str(path), prep.data)
        elif f.key == "RData":
            import pyreadr
            pyreadr.write_rdata(str(path), prep.data, df_name=_r_object_name(base))
    except PermissionError as exc:
        raise SurveyCleanError(f"Cannot write {path.name}. If it is open in another program "
                               "(such as Excel), close it and try again.") from exc
    except SurveyCleanError:
        raise
    except Exception as exc:
        if path.exists():
            path.unlink(missing_ok=True)
        raise SurveyCleanError(f"Could not write the {f.label} file: {exc}") from exc
    return path, prep.notes
