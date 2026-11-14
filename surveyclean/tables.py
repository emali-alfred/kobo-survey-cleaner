"""Read survey exports that may contain repeat groups, and reshape them.

A survey with repeat groups (household members, plots, ...) is exported as one
main table (one row per submission) plus one table per repeat group (one row per
member, plot, ...), each linked to its parent. Two export layouts are supported:

* KoboToolbox Excel export: the first sheet is the main table, every other
  sheet is a repeat group with `_index` (row id), `_parent_index` (the parent
  row's `_index`) and `_parent_table_name` (the parent sheet).
* ODK Central CSV export (a .zip or several .csv files): every table has a
  `KEY` and repeat tables a `PARENT_KEY` pointing at their parent's `KEY`.
* Wide ("side by side") export, e.g. Kobo's single-sheet CSV: one row per
  submission, with the repeat group's columns repeated once per record:
  `age, gender, age, gender, ...` (read as `age, gender, age.1, gender.1`) or
  `participants[1]/age, participants[2]/age, ...`. These are stacked back into
  a repeat-group table first. The XLSForm, when given, confirms which
  questions belong to which repeat group.

`reshape_long` merges a chain of tables (main -> repeat -> nested repeat) into
one long table: one row per record of the chosen repeat group, with the
parent's answers repeated on each row. Parents without any child rows are kept
(with empty child columns), so no submission is lost.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .errors import SurveyCleanError

KEY, PARENT_KEY = "__key", "__parent_key"
DATA_SUFFIXES = {".csv", ".txt", ".tsv", ".xlsx", ".xlsm", ".xls", ".zip"}

# Columns Kobo adds to repeat-group sheets; they repeat information that the
# parent row already holds.
_KOBO_CHILD_SYSTEM = re.compile(r"^(_index|_parent_index|_parent_table_name|_submission_.*)$")


@dataclass
class Table:
    name: str
    data: pd.DataFrame
    parent: str | None = None  # None for the main table

    @property
    def rows(self) -> int:
        return len(self.data)


@dataclass
class Survey:
    tables: dict[str, Table] = field(default_factory=dict)
    main: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def repeats(self) -> list[Table]:
        return [t for t in self.tables.values() if t.parent is not None]

    def path_to(self, name: str) -> list[str]:
        """Table names from the main table down to `name`."""
        chain = []
        cur = name
        while cur is not None:
            if cur in chain:
                raise SurveyCleanError(f"Repeat group '{name}' has a circular parent link.")
            chain.append(cur)
            cur = self.tables[cur].parent
        return chain[::-1]

    def default_level(self) -> str:
        """Long format for the first repeat group (its deepest nested repeat),
        or the main table when there are none."""
        if not self.repeats:
            return self.main
        level = self.repeats[0].name
        while True:
            kids = [t.name for t in self.repeats if t.parent == level]
            if not kids:
                return level
            level = kids[0]

    def describe(self) -> list[dict]:
        out = []
        for t in self.tables.values():
            out.append({"name": t.name, "parent": t.parent, "rows": t.rows,
                        "columns": t.data.shape[1] - sum(c in (KEY, PARENT_KEY) for c in t.data.columns)})
        return out


# --- reading -------------------------------------------------------------------

def _read_csv_text(raw: bytes, name: str) -> pd.DataFrame:
    if not raw.strip():
        raise SurveyCleanError(f"{name} is empty.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # files re-saved in Excel on Windows
        text = raw.decode("cp1252")
    try:
        sep = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
    except csv.Error:
        sep = ","
    try:
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str)
    except (pd.errors.ParserError, csv.Error, ValueError) as exc:
        raise SurveyCleanError(f"{name} could not be read as a table ({exc}).") from exc


def _check_table(df: pd.DataFrame, name: str) -> pd.DataFrame:
    if df.shape[1] < 2 or df.empty:
        raise SurveyCleanError(f"{name} has {df.shape[1]} column(s) and {len(df)} row(s): "
                               "that does not look like a survey export.")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _read_one(path: Path) -> dict[str, pd.DataFrame]:
    """Read a file into {table name: DataFrame}, keeping sheet / file order."""
    if not path.exists():
        raise SurveyCleanError(f"Data file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in DATA_SUFFIXES:
        raise SurveyCleanError(f"{path.name} is not a survey export. Choose the .csv, .xlsx or .zip "
                               "file downloaded from KoboToolbox or ODK.")
    if path.stat().st_size == 0:
        raise SurveyCleanError(f"{path.name} is empty.")
    try:
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            sheets = pd.read_excel(path, sheet_name=None, dtype=str)
            sheets = {n: d for n, d in sheets.items() if not d.dropna(how="all").empty}
            if not sheets:
                raise SurveyCleanError(f"{path.name} has no data.")
            return {n: _check_table(d, f"{path.name} / sheet '{n}'") for n, d in sheets.items()}
        if suffix == ".zip":
            out = {}
            with zipfile.ZipFile(path) as z:
                for info in sorted(z.infolist(), key=lambda i: (i.filename.count("/"), i.filename)):
                    if info.filename.lower().endswith(".csv") and not info.is_dir():
                        stem = Path(info.filename).stem
                        out[stem] = _check_table(_read_csv_text(z.read(info), info.filename), info.filename)
            if not out:
                raise SurveyCleanError(f"{path.name} contains no CSV files.")
            return out
        return {path.stem: _check_table(_read_csv_text(path.read_bytes(), path.name), path.name)}
    except SurveyCleanError:
        raise
    except ImportError as exc:
        raise SurveyCleanError(f"Cannot read {path.name}: {exc}. Save it as .xlsx or .csv.") from exc
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise SurveyCleanError(f"{path.name} could not be read. Is it the export downloaded "
                               f"from KoboToolbox or ODK? ({exc})") from exc


def _link_kobo(frames: dict[str, pd.DataFrame], main: str) -> dict[str, Table] | None:
    """Kobo Excel layout: repeat sheets carry _parent_index / _parent_table_name."""
    repeats = {n: d for n, d in frames.items() if n != main and "_parent_index" in d.columns}
    if not repeats:
        return None
    names = list(frames)
    tables = {}
    m = frames[main].copy()
    m[KEY] = m["_index"] if "_index" in m.columns else [str(i + 1) for i in range(len(m))]
    tables[main] = Table(main, m)
    for name, d in repeats.items():
        d = d.copy()
        parent_name = None
        if "_parent_table_name" in d.columns and d["_parent_table_name"].notna().any():
            parent_name = str(d["_parent_table_name"].dropna().iloc[0]).strip()
        # Sheet names are cut at 31 characters, so match on the start too.
        parent = next((n for n in names if n == parent_name), None) or \
            next((n for n in names if parent_name and parent_name.startswith(n)), None) or main
        if parent not in repeats and parent != main:
            parent = main
        d[KEY] = d["_index"] if "_index" in d.columns else [str(i + 1) for i in range(len(d))]
        d[PARENT_KEY] = d["_parent_index"]
        d = d.drop(columns=[c for c in d.columns if _KOBO_CHILD_SYSTEM.match(c)])
        tables[name] = Table(name, d, parent)
    return tables


def _link_odk(frames: dict[str, pd.DataFrame], main: str) -> dict[str, Table] | None:
    """ODK Central layout: KEY on every table, PARENT_KEY on repeat tables."""
    if not all("KEY" in d.columns for d in frames.values()):
        return None
    if not any("PARENT_KEY" in d.columns for n, d in frames.items() if n != main):
        return None
    owner = {}
    for name, d in frames.items():
        for k in d["KEY"].dropna():
            owner[k] = name
    tables = {}
    for name, d in frames.items():
        d = d.copy()
        d[KEY] = d["KEY"]
        parent = None
        if name != main and "PARENT_KEY" in d.columns:
            d[PARENT_KEY] = d["PARENT_KEY"]
            first = d["PARENT_KEY"].dropna()
            parent = owner.get(first.iloc[0], main) if not first.empty else main
            d = d.drop(columns=["KEY", "PARENT_KEY"])
        tables[name] = Table(name, d, parent)
    return tables


_DUPLICATE_HEADER = re.compile(r"^(?P<base>.+)\.(?P<n>\d+)$")  # "age.3": 4th "age" column
_INDEXED_HEADER = re.compile(r"^(?:(?P<pre>.*)/)?(?P<group>[^/\[\]]+)\[(?P<n>\d+)\]/(?P<rest>.+)$")


def _short(column: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", column.split("/")[-1]).strip("_").lower()


def _unstack_wide(df: pd.DataFrame, name: str, form=None) -> tuple[dict[str, Table], list[str]] | None:
    """Stack a repeat group stored side by side (one block of columns per record)
    into its own table. Returns None when the table has no such block."""
    cols = [str(c) for c in df.columns]
    colset = set(cols)
    parsed: dict[str, tuple[str | None, str, int]] = {}  # column -> (group, base name, record no.)
    for c in cols:
        if c.startswith("_"):
            continue
        m = _INDEXED_HEADER.match(c)
        if m:
            parsed[c] = (m["group"], m["rest"], int(m["n"]))
            continue
        m = _DUPLICATE_HEADER.match(c)
        if m and m["base"] in colset:
            parsed[c] = (None, m["base"], int(m["n"]) + 1)
        else:
            parsed[c] = (None, c, 1)

    # Questions the XLSForm places inside a repeat group: {short name: group}.
    in_repeat = {q.name: q.repeat for q in getattr(form, "questions", {}).values() if q.repeat}
    records: dict[tuple, set[int]] = {}
    for g, base, k in parsed.values():
        records.setdefault((g, base), set()).add(k)
    repeating = {gb for gb, ks in records.items()
                 if gb[0] is not None or max(ks) > 1 or _short(gb[1]) in in_repeat}
    if not repeating:
        return None

    plain = [b for g, b in repeating if g is None and _short(b) not in in_repeat]
    prefixes = {b.split("/")[0] for b in plain if "/" in b}
    fallback = prefixes.pop() if len(prefixes) == 1 and all("/" in b for b in plain) else "repeat_group"

    def group_of(g: str | None, base: str) -> str:
        return g or in_repeat.get(_short(base)) or fallback

    main_cols = [c for c in cols if c not in parsed or (parsed[c][0], parsed[c][1]) not in repeating]
    main_df = df[main_cols].copy()
    main_df[KEY] = main_df["_index"].astype(str) if "_index" in main_df.columns else \
        [str(i + 1) for i in range(len(df))]
    tables = {name: Table(name, main_df)}
    notes = []

    groups: dict[str, list[str]] = {}
    for c in cols:
        if c in parsed and (parsed[c][0], parsed[c][1]) in repeating:
            groups.setdefault(group_of(parsed[c][0], parsed[c][1]), []).append(c)
    for gname, gcols in groups.items():
        bases = list(dict.fromkeys(parsed[c][1] for c in gcols))
        slots = sorted({parsed[c][2] for c in gcols})
        parts = []
        for k in slots:
            at_k = {parsed[c][1]: c for c in gcols if parsed[c][2] == k}
            part = pd.DataFrame({b: df[at_k[b]] if b in at_k else pd.Series(None, index=df.index, dtype=object)
                                 for b in bases})
            part[PARENT_KEY] = main_df[KEY].to_numpy()
            part["__row"] = range(len(df))
            part["__slot"] = k
            parts.append(part)
        child = pd.concat(parts, ignore_index=True)
        child = child[child[bases].notna().any(axis=1)]  # empty slots are not records
        child = child.sort_values(["__row", "__slot"], kind="stable")
        child[KEY] = child[PARENT_KEY].astype(str) + "#" + child["__slot"].astype(str)
        child = child.drop(columns=["__row", "__slot"]).reset_index(drop=True)
        tname = gname if gname not in tables else f"{gname}_records"
        tables[tname] = Table(tname, child, parent=name)
        notes.append(f"Repeat group '{tname}' was stored side by side ({len(slots)} column blocks of "
                     f"{len(bases)} questions); it was stacked into {len(child):,} records.")
    return tables, notes


def load_survey(data, form=None) -> Survey:
    """Read one or more export files (or DataFrames) into a Survey.

    `data` may be a path, a list of paths, a DataFrame or a {name: DataFrame} dict.
    The main table is the first one not linked to a parent. `form` (an XLSForm)
    helps recognise repeat groups that are stored side by side."""
    if isinstance(data, pd.DataFrame):
        frames = {"main": data.copy()}
    elif isinstance(data, dict):
        frames = {str(k): v.copy() for k, v in data.items()}
    else:
        paths = [data] if isinstance(data, (str, Path)) else list(data)
        if not paths:
            raise SurveyCleanError("Choose the data export to clean first.")
        frames = {}
        for p in paths:
            for name, df in _read_one(Path(p)).items():
                key = name
                n = 2
                while key in frames:
                    key = f"{name}_{n}"
                    n += 1
                frames[key] = df
    if not frames:
        raise SurveyCleanError("No data found.")
    # The main table is the first one that is not linked to a parent.
    linked = {"_parent_index", "PARENT_KEY"}
    main = next((n for n, d in frames.items() if not linked & set(d.columns)), next(iter(frames)))
    frames = {main: frames[main], **{n: d for n, d in frames.items() if n != main}}
    tables = _link_kobo(frames, main) or _link_odk(frames, main)
    notes: list[str] = []
    if tables is None:
        if len(frames) > 1:
            extra = ", ".join(list(frames)[1:])
            raise SurveyCleanError(
                f"Several tables were given ({', '.join(frames)}) but they are not linked as repeat "
                f"groups (no _parent_index or PARENT_KEY columns). Clean them one at a time, or "
                f"remove: {extra}.")
        wide = _unstack_wide(frames[main], main, form)
        if wide is not None:
            tables, notes = wide
        else:
            tables = {main: Table(main, frames[main])}
    return Survey(tables=tables, main=main, notes=notes)


# --- reshaping -----------------------------------------------------------------

def reshape_long(survey: Survey, level: str | None = None,
                 id_col: str = "_uuid") -> tuple[pd.DataFrame, str, dict[str, str]]:
    """Merge the tables from the main table down to `level` into one long table.

    Returns the table, the name of its row-id column, and which table each
    column came from. Repeat groups that are not on the chosen path are
    summarised as `n_<group>` counts per row."""
    level = level or survey.main
    if level not in survey.tables:
        raise SurveyCleanError(f"Unknown table '{level}'. Choose one of: {', '.join(survey.tables)}.")
    path = survey.path_to(level)

    main = survey.tables[survey.main].data.copy()
    if id_col not in main.columns:
        main[id_col] = main[KEY] if KEY in main.columns else [str(i + 1) for i in range(len(main))]
    df = main
    df["_record"] = df[id_col].astype("string")
    origins = {c: survey.main for c in df.columns}
    key_col = f"{KEY}{survey.main}"
    if KEY in df.columns:
        df = df.rename(columns={KEY: key_col})

    for child_name in path[1:]:
        child = survey.tables[child_name].data.copy()
        child_key = f"{KEY}{child_name}"
        child = child.rename(columns={KEY: child_key})
        clash = (set(child.columns) & set(df.columns)) - {PARENT_KEY}
        child = child.rename(columns={c: f"{c}_{child_name}" for c in clash})
        origins.update({c: child_name for c in child.columns})
        df = df.merge(child, how="left", left_on=key_col, right_on=PARENT_KEY, validate="one_to_many")
        df = df.drop(columns=[PARENT_KEY])
        # A readable, unique id per row: <submission>/<group>[<n>]
        n = df.groupby("_record", sort=False).cumcount() + 1
        has_child = df[child_key].notna()
        df["_record"] = df["_record"].where(~has_child, df["_record"] + "/" + child_name + "[" + n.astype(str) + "]")
        key_col = child_key

    # Repeat groups off the chosen path: count their records per row.
    on_path = set(path)
    for t in survey.repeats:
        if t.name in on_path or t.parent not in on_path:
            continue
        counts = t.data[PARENT_KEY].value_counts()
        parent_key_col = f"{KEY}{t.parent}"
        df[f"n_{t.name}"] = df[parent_key_col].map(counts).fillna(0).astype("Int64")
        origins[f"n_{t.name}"] = t.parent

    df = df.drop(columns=[c for c in df.columns if c.startswith(KEY)])
    cols = ["_record"] + [c for c in df.columns if c != "_record"]
    origins["_record"] = level
    return df[cols].reset_index(drop=True), "_record", {c: origins.get(c, level) for c in cols}
