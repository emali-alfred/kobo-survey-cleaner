"""The plain-language data quality report.

It is written as the "Data Quality Report" sheet of the Excel export
(`quality_report_rows`); `build_report` (Markdown) and `build_html_report`
give the same content as text, e.g. for a preview on screen."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .pipeline import CleaningResult


@dataclass
class Section:
    heading: str
    intro: str
    table: pd.DataFrame | None


def _num(x) -> str:
    return "" if pd.isna(x) else f"{x:g}"


def summary_rows(res: CleaningResult) -> list[tuple[str, object]]:
    rows_in, cols_in = res.raw_shape
    rows_out, cols_out = res.data.shape
    rows = [("Submissions received", rows_in),
            ("Duplicate submissions removed", len(res.duplicates)),
            ("Submissions after cleaning", res.submissions)]
    if len(res.level_path) > 1:
        rows.append(("One row per", f"{res.level} record (long format: {' → '.join(res.level_path)})"))
        rows.append(("Rows in the clean data", rows_out))
    rows += [
        ("Columns received → after cleaning", f"{cols_in} → {cols_out}"),
        ("System columns dropped", len(res.dropped_metadata)),
        ("Missing codes (-99, \"don't know\", ...) recoded", sum(res.recoded_missing.values())),
        ("Values that could not be read as numbers/dates", sum(res.type_failures.values())),
        ("Multi-select answers split into 0/1 columns", len(res.multi_columns)),
        ("Possible outliers to check", len(res.outliers)),
        ("Consistency rule violations", len(res.rule_violations)),
    ]
    if "duration_min" in res.data.columns:
        per_sub = res.data.drop_duplicates("_uuid") if "_uuid" in res.data.columns else res.data
        rows.append(("Median interview length (minutes)", _num(per_sub["duration_min"].median())))
    if res.enumerator_col:
        rows.append(("Enumerators", len(res.enumerators)))
    return rows


def sections(res: CleaningResult) -> list[Section]:
    dup_cols = [c for c in ["_uuid", "_submission_time", res.enumerator_col]
                if c and c in res.duplicates.columns]
    secs = []
    if len(res.tables) > 1:
        t = pd.DataFrame(res.tables).rename(columns={"name": "table", "parent": "linked to"})
        t["linked to"] = t["linked to"].fillna("(main table)")
        secs.append(Section("Tables in the export",
                            "The main table and its repeat groups, as received (before removing duplicates).", t))
    if res.enumerator_col:
        secs.append(Section(
            f"Enumerator summary (by '{res.enumerator_col}')",
            "Workload, speed, missing answers and flags per enumerator, most flags first. "
            "Use it to target support and call-backs.", res.enumerators))
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


# --- Excel sheet ----------------------------------------------------------------

def _cell(v):
    if v is None or v is pd.NA or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.tz_localize(None).to_pydatetime() if v.tzinfo else v.to_pydatetime()
    return v.item() if hasattr(v, "item") else v


def quality_report_rows(res: CleaningResult, title: str, notes: list[str] | None = None,
                        findings: list | None = None):
    """Rows for the 'Data Quality Report' sheet as (kind, values) pairs."""
    from .advisor import findings_table
    yield "title", [title or "Data quality report"]
    yield "text", [f"Generated {datetime.now():%Y-%m-%d %H:%M}"]
    yield "text", ["Outliers and rule violations are listed on their own sheets."]
    for w in list(res.warnings) + list(notes or []):
        yield "text", [f"Note: {w}"]
    yield "blank", []
    yield "heading", ["Summary"]
    for k, v in summary_rows(res):
        yield "text", [k, v]
    checks = findings_table(findings if findings is not None else res.findings)
    yield "blank", []
    yield "heading", ["Checks and suggestions"]
    yield "text", ["What the app found at each step (most serious first within each step) and what to do about it."]
    if checks.empty:
        yield "text", ["Nothing to report."]
    else:
        yield "header", [c for c in checks.columns]
        for row in checks.itertuples(index=False):
            yield "row", list(row)
    for s in sections(res):
        yield "blank", []
        yield "heading", [s.heading]
        if s.intro:
            yield "text", [s.intro]
        if s.table is None or s.table.empty:
            yield "text", ["None found."]
            continue
        yield "header", [str(c) for c in s.table.columns]
        for row in s.table.itertuples(index=False):
            yield "row", [_cell(v) for v in row]


# --- Markdown / HTML (previews) -----------------------------------------------------

def _md_table(df: pd.DataFrame | None, limit: int = 50) -> str:
    if df is None or df.empty:
        return "_None found._\n"
    shown = df.head(limit)
    header = "| " + " | ".join(map(str, shown.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in shown.columns) + " |"
    body = "\n".join("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
                     for row in shown.itertuples(index=False))
    more = f"\n\n_...and {len(df) - limit} more._" if len(df) > limit else ""
    return f"{header}\n{sep}\n{body}{more}\n"


def build_report(res: CleaningResult, title: str = "Data quality report") -> str:
    lines = [f"# {title}", f"_Generated {datetime.now():%Y-%m-%d %H:%M}_", ""]
    if res.warnings:
        lines += ["> **Warnings**", ">"] + [f"> - {w}" for w in res.warnings] + [""]
    lines += ["## Summary", "", "| | Count |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in summary_rows(res)]
    for heading, intro, table in [
        ("Consistency checks", "Records that break a logic rule.", res.rule_violations),
        ("Possible outliers", "Extreme values are flagged, not deleted.", res.outliers),
    ] + [(s.heading, s.intro, s.table) for s in sections(res)]:
        lines += ["", f"## {heading}"] + ([intro] if intro else []) + ["", _md_table(table)]
    return "\n".join(lines)


def build_html_report(res: CleaningResult, title: str = "Data quality report") -> str:
    esc = html.escape

    def table(df):
        if df is None or df.empty:
            return "<p><em>None found.</em></p>"
        head = "".join(f"<th>{esc(str(c))}</th>" for c in df.columns)
        body = "".join("<tr>" + "".join(f"<td>{'' if pd.isna(v) else esc(str(v))}</td>" for v in r) + "</tr>"
                       for r in df.head(200).itertuples(index=False))
        return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    parts = [f"<h2>{esc(h)}</h2>{f'<p>{esc(i)}</p>' if i else ''}{table(t)}" for h, i, t in [
        ("Consistency checks", "Records that break a logic rule.", res.rule_violations),
        ("Possible outliers", "Extreme values are flagged, not deleted.", res.outliers),
    ] + [(s.heading, s.intro, s.table) for s in sections(res)]]
    summary = pd.DataFrame(summary_rows(res), columns=["", "Count"]).astype(str)
    warn = "".join(f'<p class="warn">{esc(w)}</p>' for w in res.warnings)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>:root{{--bg:#fff;--fg:#1d2433;--line:#e3e7ee;--head:#f4f6f9;--warn:#fff6e0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171c;--fg:#e6e9ef;--line:#2c323c;--head:#1c2027;--warn:#3a3014}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Segoe UI",sans-serif}}
h1{{font-size:22px}}h2{{font-size:17px;margin-top:28px}}.tw{{overflow-x:auto}}
table{{border-collapse:collapse}}th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{background:var(--head)}}.warn{{background:var(--warn);padding:8px 12px;border-radius:6px}}</style></head>
<body><h1>{esc(title)}</h1>{warn}<h2>Summary</h2>{table(summary)}{''.join(parts)}</body></html>"""
