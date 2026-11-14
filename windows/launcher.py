"""Entry point for the standalone Windows program (bundled by PyInstaller).

"Survey Cleaner.exe --selftest <file>" cleans the built-in demo survey without
opening a window, exports it in every format and writes a summary to <file>;
the build uses it to check the bundled program really works.
"""

import contextlib
import sys
import tempfile


def selftest(report_path: str) -> int:
    from surveyclean import export_file, run
    from surveyclean.cli import demo_files
    from surveyclean.export import FORMATS

    with open(report_path, "w", encoding="utf-8") as fh, \
            contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
        try:
            d = demo_files()
            res = run(d["data"], form=d["form"], rules=d["rules"])
            print(f"Rows {len(res.data)}, submissions {res.submissions}, "
                  f"outliers {len(res.outliers)}, rule violations {len(res.rule_violations)}")
            out = tempfile.mkdtemp(prefix="surveyclean-selftest-")
            for key, fmt in FORMATS.items():
                if not fmt.available:
                    print(f"SELFTEST MISSING WRITER {key} ({fmt.needs})")
                    return 1
                path, _ = export_file(res, out, "selftest", key)
                print(f"  {key:6} {path.stat().st_size:>9,} bytes")
        except Exception as exc:  # report, don't crash silently in a windowed exe
            print(f"SELFTEST ERROR: {exc!r}")
            return 1
        print("SELFTEST EXIT 0")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    from surveyclean.gui import main
    main()
