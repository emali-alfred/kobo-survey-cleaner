"""Command line.

    surveyclean export.xlsx --form form.xlsx --rules rules.yaml \\
        --name "Baseline 2026" --format xlsx --out results

Writes exactly ONE file: <out>/<name>.<format extension>.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from importlib import resources
from pathlib import Path

from . import __version__
from .advisor import STEP_NAMES, check_export
from .errors import SurveyCleanError
from .export import FORMATS, NAME_REQUIRED, clean_filename, export_file
from .pipeline import inspect, run


def demo_files() -> dict[str, Path]:
    """Paths to the synthetic demo survey shipped with the package
    (households with a household-member repeat group)."""
    base = Path(str(resources.files("surveyclean") / "demo"))
    return {"data": base / "sample_raw_export.xlsx", "form": base / "sample_form.xlsx",
            "rules": base / "rules.yaml"}


def open_file(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens with the default app
    else:
        webbrowser.open(path.resolve().as_uri())


def _rename_pairs(items: list[str] | None) -> dict[str, str]:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SurveyCleanError(f"--rename needs OLD=NEW, got '{item}'.")
        old, new = item.split("=", 1)
        out[old.strip()] = new.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="surveyclean",
        description="Clean a KoboToolbox/ODK export and save it as ONE file in the format you choose.")
    p.add_argument("data", nargs="*", help="Raw export: .xlsx (with repeat-group sheets), .csv, or "
                                           "ODK Central's .zip / several .csv files")
    p.add_argument("--form", help="XLSForm used to collect the data (.xlsx): types and answer labels")
    p.add_argument("--rules", help="YAML file of consistency rules")
    p.add_argument("--name", help="Output file name, without extension (required)")
    p.add_argument("--format", default="xlsx", choices=list(FORMATS),
                   help="Output format (default: xlsx). xlsx also holds outliers, rule violations "
                        "and the data quality report; the others hold the clean data only.")
    p.add_argument("--out", default=".", help="Folder to save the file in (default: current folder)")
    p.add_argument("--level", help="Row level: the main table or a repeat group name "
                                   "(default: the first repeat group, in long format)")
    p.add_argument("--list-tables", action="store_true", help="Show the main table and repeat groups, then stop")
    p.add_argument("--rename", nargs="+", metavar="OLD=NEW", help="Rename variables, e.g. hh_size=household_size")
    p.add_argument("--keep", nargs="+", metavar="VAR",
                   help="Export only these variables (default: all), e.g. --keep _record county age")
    p.add_argument("--all-checks", action="store_true",
                   help="Also print the 'note' level checks, not only problems and warnings")
    p.add_argument("--codes", action="store_true", help="Keep answer codes instead of XLSForm labels")
    p.add_argument("--id-col", default="_uuid", help="Unique submission ID column (default: _uuid)")
    p.add_argument("--enumerator-col",
                   help="Column naming the enumerator (default: auto-detect 'enumerator', 'username', ...)")
    p.add_argument("--short-minutes", type=float, default=10.0,
                   help="Interviews shorter than this are counted per enumerator (default: 10)")
    p.add_argument("--outlier-k", type=float, default=3.0, help="IQR multiplier for outliers (default: 3)")
    p.add_argument("--title", help="Title for the report sheet / HTML page (default: the file name)")
    p.add_argument("--open", action="store_true", help="Open the file when done")
    p.add_argument("--demo", action="store_true", help="Use the built-in synthetic demo survey")
    p.add_argument("--version", action="version", version=f"surveyclean {__version__}")
    a = p.parse_args(argv)

    if a.demo:
        d = demo_files()
        a.data, a.form, a.rules = [d["data"]], a.form or d["form"], a.rules or d["rules"]
    if not a.data:
        p.error("give the export file to clean, or use --demo")

    try:
        if a.list_tables:
            survey = inspect(a.data, a.form)
            for note in survey.notes:
                print(f"Note: {note}")
            for t in survey.describe():
                parent = f"repeat group of '{t['parent']}'" if t["parent"] else "main table"
                print(f"  {t['name']}: {t['rows']} rows, {t['columns']} columns ({parent})")
            return 0
        if not a.name or not a.name.strip():
            raise SurveyCleanError(NAME_REQUIRED + " Use --name.")
        clean_filename(a.name)  # fail before the work if the name is unusable
        res = run(a.data, form=a.form, rules=a.rules, id_col=a.id_col, outlier_k=a.outlier_k,
                  enumerator_col=a.enumerator_col, short_minutes=a.short_minutes, level=a.level)
        if a.keep:
            unknown = [v for v in a.keep if v not in res.data.columns]
            if unknown:
                raise SurveyCleanError(f"--keep: unknown variable(s) {', '.join(unknown)}. "
                                       f"Available: {', '.join(res.data.columns)}")
        renames = _rename_pairs(a.rename)
        export_findings = check_export(res, a.format, a.keep, renames)
        path, notes = export_file(res, a.out, a.name, a.format, rename=renames,
                                  use_labels=not a.codes, title=a.title, keep=a.keep)
    except SurveyCleanError as exc:
        msg = str(exc)
        print(msg if msg.startswith("Error:") else f"Error: {msg}", file=sys.stderr)
        return 2

    findings = res.findings + export_findings
    shown = [f for f in findings if a.all_checks or f.severity != "note"]
    if shown:
        print("Checks & suggestions:")
        for f in shown:
            print(f"  [{f.severity}] {STEP_NAMES[f.step]}: {f.title}. {f.detail}")
            if f.suggestion:
                print(f"      -> {f.suggestion}")
        hidden = len(findings) - len(shown)
        if hidden:
            print(f"  ({hidden} more notes: use --all-checks, or see the Data Quality Report sheet)")
    for w in notes:
        print(f"Note: {w}")
    level = (f", one row per '{res.level}' record ({len(res.data)} rows)"
             if len(res.level_path) > 1 else "")
    print(f"Submissions: {res.raw_shape[0]} in, {res.submissions} out "
          f"({len(res.duplicates)} duplicates removed){level}")
    print(f"Flags: {len(res.outliers)} possible outliers, {len(res.rule_violations)} rule violations")
    print(f"Saved: {path}")
    if a.open:
        open_file(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
