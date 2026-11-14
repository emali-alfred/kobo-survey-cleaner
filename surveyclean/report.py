"""Write the cleaned data and a plain-language data quality report
(Markdown, HTML and an Excel workbook)."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .pipeline import CleaningResult


@dataclass
class Section:
    heading: str
    intro: str
    table: pd.DataFrame | None


def _summary_rows(res: CleaningResult) -> list[tuple[str, object]]:
    rows_in, cols_in = res.raw_shape
    rows_out, cols_out = res.data.shape
    rows = [
        ("Records received", rows_in),
        ("Duplicate submissions removed", len(res.duplicates)),
        ("Records after cleaning", rows_out),
        ("Columns received → after cleaning", f"{cols_in} → {cols_out}"),
        ("System columns dropped", len(res.dropped_metadata)),
        ("Missing codes (-99, \"don't know\", ...) recoded", sum(res.recoded_missing.values())),
        ("Values that could not be read as numbers/dates", sum(res.type_failures.values())),
        ("Multi-select answers split into 0/1 columns", len(res.multi_columns)),
        ("Label columns added", len(res.label_columns)),
        ("Possible outliers to check", len(res.outliers)),
        ("Consistency rule violations", len(res.rule_violations)),
    ]
    if "duration_min" in res.data.columns:
        rows.append(("Median interview length (minutes)", _num(res.data["duration_min"].median())))
    if res.enumerator_col:
        rows.append(("Enumerators", len(res.enumerators)))
    return rows


def _num(x) -> str:
    return "" if pd.isna(x) else f"{x:g}"


def _sections(res: CleaningResult) -> list[Section]:
    dup_cols = [c for c in ["_uuid", "_submission_time", res.enumerator_col]
                if c and c in res.duplicates.columns]
    secs = [
        Section("Consistency checks",
                "Records that break a logic rule. These usually need a call-back to the enumerator.",
                res.rule_violations),
        Section("Possible outliers",
                "Extreme values are flagged, not deleted. Confirm them before analysis.",
                res.outliers),
    ]
    if res.enumerator_col:
        secs.append(Section(
            f"Enumerator summary (by `{res.enumerator_col}`)",
            "Workload, speed, missing answers and flags per enumerator, most flags first. "
            "Use it to target support and call-backs.",
            res.enumerators))
    secs += [
        Section("Missing data", "Share of missing answers per question (after recoding missing codes).",
                res.missing),
        Section("Missing codes recoded", "",
                pd.DataFrame(sorted(res.recoded_missing.items()), columns=["column", "values_recoded"])),
        Section("Duplicate submissions removed", "",
                res.duplicates[dup_cols] if not res.duplicates.empty and dup_cols else res.duplicates),
    ]
    if res.type_failures:
        secs.append(Section("Values that could not be converted",
                            "Answers that are not valid numbers or dates were set to missing.",
                            pd.DataFrame(sorted(res.type_failures.items()), columns=["column", "values"])))
    return secs


# --- Markdown -----------------------------------------------------------------

def _table(df: pd.DataFrame | None, limit: int = 50) -> str:
    if df is None or df.empty:
        return "_None found._\n"
    shown = df.head(limit)
    header = "| " + " | ".join(map(str, shown.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in shown.columns) + " |"
    body = "\n".join("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
                     for row in shown.itertuples(index=False))
    more = f"\n\n_...and {len(df) - limit} more (see the CSV files)._" if len(df) > limit else ""
    return f"{header}\n{sep}\n{body}{more}\n"


def build_report(res: CleaningResult, title: str = "Data quality report") -> str:
    lines = [f"# {title}", f"_Generated {datetime.now():%Y-%m-%d %H:%M}_", ""]
    if res.warnings:
        lines += ["> **Warnings**", ">"] + [f"> - {w}" for w in res.warnings] + [""]
    lines += ["## Summary", "", "| | Count |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in _summary_rows(res)]
    lines.append("")
    for s in _sections(res):
        lines.append(f"## {s.heading}")
        if s.intro:
            lines.append(s.intro)
        lines += ["", _table(s.table)]
    return "\n".join(lines)


# --- HTML ---------------------------------------------------------------------

_CSS = """
:root{--bg:#fff;--fg:#1d2433;--muted:#5c667a;--line:#e3e7ee;--head:#f4f6f9;--accent:#1f6feb;
--warn-bg:#fff6e0;--warn-line:#e7b416;--good:#1a7f37;--bad:#c62828}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ef;--muted:#9aa4b5;--line:#2c323c;
--head:#1c2027;--accent:#58a6ff;--warn-bg:#3a3014;--warn-line:#b38a12;--good:#3fb950;--bad:#f85149}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 6px;padding-top:8px;border-top:1px solid var(--line)}
.muted{color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin:18px 0}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card .n{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}.card .l{font-size:13px;color:var(--muted)}
.card.flag .n{color:var(--bad)}.card.ok .n{color:var(--good)}
.warn{background:var(--warn-bg);border-left:4px solid var(--warn-line);padding:10px 14px;border-radius:6px;margin:14px 0}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--head);font-weight:600;position:sticky;top:0}tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle;margin-right:8px}
nav a{color:var(--accent);text-decoration:none;margin-right:14px;font-size:14px}
"""


def _html_table(df: pd.DataFrame | None, limit: int = 200, bar_col: str | None = None) -> str:
    if df is None or df.empty:
        return '<p class="muted"><em>None found.</em></p>'
    shown = df.head(limit)
    numeric = {c for c in shown.columns if pd.api.types.is_numeric_dtype(shown[c])}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in shown.columns)
    body = []
    for row in shown.itertuples(index=False):
        cells = []
        for c, v in zip(shown.columns, row):
            text = "" if pd.isna(v) else html.escape(str(v))
            if c == bar_col and not pd.isna(v):
                text = f'<span class="bar" style="width:{min(float(v), 100):.0f}px"></span>{text}%'
            cls = ' class="num"' if c in numeric else ""
            cells.append(f"<td{cls}>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    more = (f'<p class="muted">…and {len(df) - limit} more (see the CSV / Excel files).</p>'
            if len(df) > limit else "")
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{more}'


def build_html_report(res: CleaningResult, title: str = "Data quality report") -> str:
    esc = html.escape
    cards = [
        ("Records after cleaning", len(res.data), ""),
        ("Duplicates removed", len(res.duplicates), "flag" if len(res.duplicates) else "ok"),
        ("Rule violations", len(res.rule_violations), "flag" if len(res.rule_violations) else "ok"),
        ("Possible outliers", len(res.outliers), "flag" if len(res.outliers) else "ok"),
        ("Missing codes recoded", sum(res.recoded_missing.values()), ""),
        ("Unreadable values", sum(res.type_failures.values()),
         "flag" if res.type_failures else "ok"),
    ]
    card_html = "".join(f'<div class="card {cls}"><div class="n">{n:,}</div><div class="l">{esc(l)}</div></div>'
                        for l, n, cls in cards)
    warn = ""
    if res.warnings:
        warn = '<div class="warn"><strong>Warnings</strong><ul>' + "".join(
            f"<li>{esc(w)}</li>" for w in res.warnings) + "</ul></div>"
    summary = pd.DataFrame(_summary_rows(res), columns=["", "Count"])
    summary["Count"] = summary["Count"].astype(str)
    parts, nav = [], []
    for i, s in enumerate(_sections(res)):
        anchor = f"s{i}"
        heading = s.heading.replace("`", "")
        nav.append(f'<a href="#{anchor}">{esc(heading)}</a>')
        intro = f'<p class="muted">{esc(s.intro)}</p>' if s.intro else ""
        bar = "missing_pct" if s.heading == "Missing data" else None
        parts.append(f'<h2 id="{anchor}">{esc(heading)}</h2>{intro}{_html_table(s.table, bar_col=bar)}')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{_CSS}</style></head>
<body><main>
<h1>{esc(title)}</h1><p class="muted">Generated {datetime.now():%Y-%m-%d %H:%M}</p>
{warn}<div class="cards">{card_html}</div>
<nav>{"".join(nav)}</nav>
<h2>Summary</h2>{_html_table(summary)}
{"".join(parts)}
</main></body></html>
"""


# --- Excel --------------------------------------------------------------------

def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Excel cannot store time zones: write local clock time instead."""
    out = df.copy()
    for c in out.columns:
        if isinstance(out[c].dtype, pd.DatetimeTZDtype):
            out[c] = out[c].dt.tz_localize(None)
    return out


def write_excel(res: CleaningResult, path: Path) -> None:
    sheets = {
        "clean_data": res.data,
        "rule_violations": res.rule_violations,
        "outliers": res.outliers,
        "missing_data": res.missing,
    }
    if res.enumerator_col:
        sheets["enumerators"] = res.enumerators
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summary = pd.DataFrame(_summary_rows(res), columns=["item", "count"])
        summary["count"] = summary["count"].astype(str)
        summary.to_excel(xw, sheet_name="summary", index=False)
        for name, df in sheets.items():
            _excel_safe(df).to_excel(xw, sheet_name=name, index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col[:200] if c.value is not None), default=8)
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 8), 50)


def write_outputs(res: CleaningResult, out_dir: str | Path, title: str = "Data quality report",
                  excel: bool = True) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "clean_csv": out / "clean_data.csv",
        "report": out / "data_quality_report.md",
        "html": out / "data_quality_report.html",
        "outliers": out / "outliers.csv",
        "violations": out / "rule_violations.csv",
    }
    res.data.to_csv(paths["clean_csv"], index=False, encoding="utf-8-sig")  # BOM: opens cleanly in Excel
    res.outliers.to_csv(paths["outliers"], index=False, encoding="utf-8-sig")
    res.rule_violations.to_csv(paths["violations"], index=False, encoding="utf-8-sig")
    if res.enumerator_col:
        paths["enumerators"] = out / "enumerator_summary.csv"
        res.enumerators.to_csv(paths["enumerators"], index=False, encoding="utf-8-sig")
    paths["report"].write_text(build_report(res, title), encoding="utf-8")
    paths["html"].write_text(build_html_report(res, title), encoding="utf-8")
    if excel:
        paths["excel"] = out / "clean_data.xlsx"
        write_excel(res, paths["excel"])
    return paths
