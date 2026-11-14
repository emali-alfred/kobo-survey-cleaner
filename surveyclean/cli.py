"""Command line: surveyclean raw_export.csv --form form.xlsx --rules rules.yaml --out output/"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from importlib import resources
from pathlib import Path

from . import __version__
from .pipeline import SurveyCleanError, run
from .report import write_outputs


def demo_files() -> dict[str, Path]:
    """Paths to the synthetic demo survey shipped with the package."""
    base = Path(str(resources.files("surveyclean") / "demo"))
    return {"data": base / "sample_raw_export.csv", "form": base / "sample_form.xlsx",
            "rules": base / "rules.yaml"}


def open_file(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens with the default app
    else:
        webbrowser.open(path.resolve().as_uri())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="surveyclean",
                                description="Clean a KoboToolbox/ODK export and write a data quality report.")
    p.add_argument("data", nargs="?", help="Raw export (.csv or .xlsx)")
    p.add_argument("--form", help="XLSForm used to collect the data (.xlsx)")
    p.add_argument("--rules", help="YAML file of consistency rules")
    p.add_argument("--out", default="output", help="Folder for results (default: output)")
    p.add_argument("--id-col", default="_uuid", help="Unique submission ID column (default: _uuid)")
    p.add_argument("--enumerator-col",
                   help="Column naming the enumerator (default: auto-detect 'enumerator', 'username', ...)")
    p.add_argument("--short-minutes", type=float, default=10.0,
                   help="Interviews shorter than this are counted per enumerator (default: 10)")
    p.add_argument("--outlier-k", type=float, default=3.0, help="IQR multiplier for outliers (default: 3)")
    p.add_argument("--title", default="Data quality report", help="Report title")
    p.add_argument("--no-excel", action="store_true", help="Do not write clean_data.xlsx")
    p.add_argument("--open", action="store_true", help="Open the HTML report when done")
    p.add_argument("--demo", action="store_true", help="Run on the built-in synthetic demo survey")
    p.add_argument("--version", action="version", version=f"surveyclean {__version__}")
    a = p.parse_args(argv)

    if a.demo:
        d = demo_files()
        a.data, a.form, a.rules = d["data"], a.form or d["form"], a.rules or d["rules"]
        if a.title == "Data quality report":
            a.title = "Livestock household survey: data quality report (synthetic demo)"
    if not a.data:
        p.error("give the export file to clean, or use --demo")

    try:
        res = run(a.data, form=a.form, rules=a.rules, id_col=a.id_col, outlier_k=a.outlier_k,
                  enumerator_col=a.enumerator_col, short_minutes=a.short_minutes)
        paths = write_outputs(res, a.out, a.title, excel=not a.no_excel)
    except SurveyCleanError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"Error: cannot write {exc.filename}. Close it in Excel and try again.", file=sys.stderr)
        return 2

    for w in res.warnings:
        print(f"Warning: {w}")
    print(f"Records: {res.raw_shape[0]} in, {len(res.data)} out "
          f"({len(res.duplicates)} duplicates removed)")
    print(f"Flags: {len(res.outliers)} possible outliers, {len(res.rule_violations)} rule violations")
    for name, path in paths.items():
        print(f"  {name:<11} {path}")
    if a.open:
        open_file(paths["html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
