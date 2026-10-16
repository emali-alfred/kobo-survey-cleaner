"""Write the cleaned data and a plain-language data quality report."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .pipeline import CleaningResult


def _table(df: pd.DataFrame, limit: int = 50) -> str:
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
    rows_in, cols_in = res.raw_shape
    rows_out, cols_out = res.data.shape
    recoded_total = sum(res.recoded_missing.values())
    lines = [
        f"# {title}",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
        "## Summary",
        "",
        "| | Count |",
        "| --- | --- |",
        f"| Records received | {rows_in} |",
        f"| Duplicate submissions removed | {len(res.duplicates)} |",
        f"| Records after cleaning | {rows_out} |",
        f"| Columns received → after cleaning | {cols_in} → {cols_out} |",
        f"| System columns dropped | {len(res.dropped_metadata)} |",
        f"| Missing codes (-99, \"don't know\", ...) recoded | {recoded_total} |",
        f"| Values that could not be read as numbers/dates | {sum(res.type_failures.values())} |",
        f"| Multi-select answers split into 0/1 columns | {len(res.multi_columns)} |",
        f"| Label columns added | {len(res.label_columns)} |",
        f"| Possible outliers to check | {len(res.outliers)} |",
        f"| Consistency rule violations | {len(res.rule_violations)} |",
        "",
        "## Consistency checks",
        "Records that break a logic rule. These usually need a call-back to the enumerator.",
        "",
        _table(res.rule_violations),
        "## Possible outliers",
        "Extreme values are flagged, not deleted. Confirm them before analysis.",
        "",
        _table(res.outliers),
        "## Missing data",
        "Share of missing answers per question (after recoding missing codes).",
        "",
        _table(res.missing),
        "## Missing codes recoded",
        "",
        _table(pd.DataFrame(sorted(res.recoded_missing.items()), columns=["column", "values_recoded"])),
        "## Duplicate submissions removed",
        "",
        _table(res.duplicates[[c for c in ["_uuid", "_submission_time"] if c in res.duplicates.columns]]
               if not res.duplicates.empty else res.duplicates),
    ]
    if res.type_failures:
        lines += ["## Values that could not be converted", "",
                  _table(pd.DataFrame(sorted(res.type_failures.items()), columns=["column", "values"]))]
    return "\n".join(lines)


def write_outputs(res: CleaningResult, out_dir: str | Path, title: str = "Data quality report") -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "clean_csv": out / "clean_data.csv",
        "report": out / "data_quality_report.md",
        "outliers": out / "outliers.csv",
        "violations": out / "rule_violations.csv",
    }
    res.data.to_csv(paths["clean_csv"], index=False)
    res.outliers.to_csv(paths["outliers"], index=False)
    res.rule_violations.to_csv(paths["violations"], index=False)
    paths["report"].write_text(build_report(res, title), encoding="utf-8")
    return paths
