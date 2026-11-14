"""Entry point for the standalone Windows program (bundled by PyInstaller).

"Survey Cleaner.exe --selftest <file>" cleans the built-in demo survey without
opening a window and writes the summary to <file>; the build uses it to check
the bundled program really works.
"""

import contextlib
import sys
import tempfile


def selftest(report_path: str) -> int:
    from surveyclean.cli import main as cli_main

    with open(report_path, "w", encoding="utf-8") as fh, \
            contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
        try:
            code = cli_main(["--demo", "--out", tempfile.mkdtemp(prefix="surveyclean-selftest-")])
        except Exception as exc:  # report, don't crash silently in a windowed exe
            print(f"SELFTEST ERROR: {exc!r}")
            return 1
        print(f"SELFTEST EXIT {code}")
    return code


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    from surveyclean.gui import main
    main()
