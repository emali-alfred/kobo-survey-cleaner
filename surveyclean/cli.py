"""Command line: surveyclean raw_export.csv --form form.xlsx --rules rules.yaml --out output/"""

from __future__ import annotations

import argparse

from .pipeline import run
from .report import write_outputs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="surveyclean",
                                description="Clean a KoboToolbox/ODK export and write a data quality report.")
    p.add_argument("data", help="Raw export (.csv or .xlsx)")
    p.add_argument("--form", help="XLSForm used to collect the data (.xlsx)")
    p.add_argument("--rules", help="YAML file of consistency rules")
    p.add_argument("--out", default="output", help="Folder for results (default: output)")
    p.add_argument("--id-col", default="_uuid", help="Unique submission ID column (default: _uuid)")
    p.add_argument("--outlier-k", type=float, default=3.0, help="IQR multiplier for outliers (default: 3)")
    p.add_argument("--title", default="Data quality report", help="Report title")
    a = p.parse_args(argv)

    res = run(a.data, form=a.form, rules=a.rules, id_col=a.id_col, outlier_k=a.outlier_k)
    paths = write_outputs(res, a.out, a.title)
    print(f"Records: {res.raw_shape[0]} in, {len(res.data)} out "
          f"({len(res.duplicates)} duplicates removed)")
    print(f"Flags: {len(res.outliers)} possible outliers, {len(res.rule_violations)} rule violations")
    for name, path in paths.items():
        print(f"  {name:<11} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
