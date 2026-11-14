"""Assemble the web app into web/_site (what GitHub Pages serves).

The site reuses the real surveyclean package: its .py files and demo data are
copied next to the page and run in the browser with Pyodide.

Run:  python web/build.py      then serve web/_site, e.g.
      python -m http.server 8000 --directory web/_site
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

WEB = Path(__file__).parent
ROOT = WEB.parent
SITE = WEB / "_site"
PKG = ROOT / "surveyclean"
SKIP_PY = {"gui.py"}  # desktop-only (tkinter)


def main() -> None:
    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir()
    for item in WEB.iterdir():
        if item.name in {"_site", "build.py", "__pycache__"}:
            continue
        dest = SITE / item.name
        shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)

    files: list[str] = []
    for f in sorted(PKG.rglob("*")):
        rel = f.relative_to(PKG).as_posix()
        if f.is_dir() or "__pycache__" in rel or f.name in SKIP_PY or rel.startswith("assets/"):
            continue
        out = SITE / "surveyclean" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        files.append(rel)

    version = re.search(r'__version__ = "([^"]+)"', (PKG / "__init__.py").read_text()).group(1)
    (SITE / "surveyclean" / "files.json").write_text(json.dumps({"version": version, "files": files}))

    # A new cache name whenever any file changes, so phones pick up updates.
    digest = hashlib.sha256()
    for f in sorted(SITE.rglob("*")):
        if f.is_file():
            digest.update(f.relative_to(SITE).as_posix().encode())
            digest.update(f.read_bytes())
    sw = SITE / "sw.js"
    sw.write_text(sw.read_text().replace("__BUILD__", digest.hexdigest()[:12]))

    (SITE / ".nojekyll").write_text("")  # let GitHub Pages serve .well-known/
    print(f"Built {SITE} (surveyclean {version}, {len(files)} package files)")


if __name__ == "__main__":
    main()
