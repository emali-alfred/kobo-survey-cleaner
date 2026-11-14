"""The Survey Cleaner desktop window: a four-step wizard.

  1 Upload           data export (with any repeat groups), XLSForm, rules
  2 Reshape          choose one row per submission, or long format per repeat group
  3 Preview & Rename see the cleaned data; choose the variables; optionally rename them
  4 Name & Export    required file name + format -> exactly one file

Every step has a compact "Checks & suggestions" bar (anomalies found and what to
do about them, see advisor.py) that opens on click. Light, dark or system
colours, chosen in the top bar and remembered (see theme.py).

Start it with `surveyclean-gui` (or `python -m surveyclean.gui`)."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import traceback
from importlib import resources
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from . import __version__, theme
from .advisor import check_export, check_reshape, check_upload
from .cli import demo_files, open_file
from .errors import SurveyCleanError
from .export import FORMATS, NAME_REQUIRED, clean_filename, export_file, prepare, variable_table
from .pipeline import inspect, load_form_checked, run

ICONS = {"problem": "✖", "warning": "▲", "note": "ℹ"}
TAB_TITLES = ["1  Upload", "2  Reshape", "3  Preview & Rename", "4  Name & Export"]
FORMAT_HELP = {
    "xlsx": "One workbook with 4 sheets: the clean data (named after your file), Outliers, "
            "Rule Violations and the Data Quality Report (including all checks & suggestions).",
    "csv": "The clean data only. Missing values are empty cells.",
    "rds": "The clean data only, for R (readRDS). Labelled answers become factors; missing values are NA.",
    "RData": "The clean data only, for R (load). Labelled answers become factors; missing values are NA.",
    "dta": "The clean data only, for Stata. Codes keep their value labels and questions their "
           "variable labels; missing numbers are '.'.",
    "sav": "The clean data only, for SPSS. Codes keep their value labels and questions their "
           "variable labels; missing numbers are system-missing.",
    "html": "The clean data only, as a table that opens in any web browser.",
}


def autowrap(label: ttk.Label, margin: int = 12) -> ttk.Label:
    """Wrap a label's text to the width it is given, at any screen scaling."""
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width - margin, 100)))
    return label


def _count_label(findings) -> str:
    serious = [f for f in findings if f.severity in ("problem", "warning")]
    return f"  ({len(serious)}⚠)" if serious else ""


class FindingsPanel(ttk.Frame):
    """Compact 'Checks & suggestions' bar: counts at a glance, details on click."""

    def __init__(self, parent, height: int = 7):
        super().__init__(parent, style="Checks.TFrame", padding=(10, 6))
        self.columnconfigure(0, weight=1)
        head = ttk.Frame(self, style="ChecksInner.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Checks & suggestions", style="Checks.TLabel").pack(side="left")
        self.chips = ttk.Frame(head, style="ChecksInner.TFrame")
        self.chips.pack(side="left", padx=(12, 0))
        self.toggle_btn = ttk.Button(head, text="Show details ▾", style="Link.TButton", command=self.toggle)
        self.toggle_btn.pack(side="right")
        self.body = ttk.Frame(self, style="ChecksInner.TFrame")
        self.body.columnconfigure(0, weight=1)
        self.text = tk.Text(self.body, height=height, wrap="word", relief="flat", borderwidth=0,
                            highlightthickness=0, padx=4, pady=4, cursor="arrow", font=("Segoe UI", 10))
        sb = ttk.Scrollbar(self.body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.grid(row=0, column=0, sticky="nsew", pady=(6, 0))
        sb.grid(row=0, column=1, sticky="ns", pady=(6, 0))
        self.open = False
        self._findings: list = []
        self.show([], "Checks appear here once the files are read.")

    def recolor(self, p: theme.Palette) -> None:
        t = self.text
        t.configure(background=p.surface_alt, foreground=p.fg, selectbackground=p.select,
                    inactiveselectbackground=p.select, insertbackground=p.fg)
        for sev, colour in (("problem", p.problem), ("warning", p.warning), ("note", p.note)):
            t.tag_configure(sev, foreground=colour, font=("Segoe UI", 10, "bold"))
        t.tag_configure("detail", foreground=p.fg)
        t.tag_configure("tip", foreground=p.ok, lmargin1=20, lmargin2=20, spacing3=4)
        t.tag_configure("head", foreground=p.brand, font=("Segoe UI", 9, "bold"), spacing1=4)
        t.tag_configure("muted", foreground=p.muted)

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self.body.grid(row=1, column=0, sticky="nsew")
        else:
            self.body.grid_remove()
        self.toggle_btn.configure(text="Hide details ▴" if self.open else "Show details ▾")

    def _chips(self, findings) -> None:
        for w in self.chips.winfo_children():
            w.destroy()
        counts = {s: sum(f.severity == s for f in findings) for s in ICONS}
        names = {"problem": ("problem", "problems"), "warning": ("warning", "warnings"), "note": ("note", "notes")}
        if not any(counts.values()):
            ttk.Label(self.chips, text="✔ All good", style="ChipOk.TLabel").pack(side="left")
            return
        for sev, n in counts.items():
            if n:
                word = names[sev][0 if n == 1 else 1]
                chip = ttk.Label(self.chips, text=f"{ICONS[sev]} {n} {word}", style=f"Chip{sev.title()}.TLabel",
                                 cursor="hand2")
                chip.pack(side="left", padx=(0, 12))
                chip.bind("<Button-1>", lambda e: self.toggle())

    def show(self, findings, empty: str = "No problems found at this step.", groups=None) -> None:
        """`groups`: optional list of (heading, findings) shown one after another."""
        groups = groups or [(None, findings)]
        self._findings = [f for _, fs in groups for f in fs]
        self._chips(self._findings)
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not self._findings:
            t.insert("end", "✔ " + empty, "muted")
        for heading, fs in groups:
            if heading and fs:
                t.insert("end", heading.upper() + "\n", "head")
            for f in fs:
                t.insert("end", f"{ICONS.get(f.severity, '•')} {f.title}", f.severity)
                if f.detail:
                    t.insert("end", f"  {f.detail}", "detail")
                t.insert("end", "\n")
                if f.suggestion:
                    t.insert("end", f"→ {f.suggestion}\n", "tip")
        t.configure(state="disabled")
        t.see("1.0")


class App(ttk.Frame):
    def __init__(self, root: tk.Misc, theme_mode: str | None = None):
        self.root = root
        self.scale = max(root.winfo_fpixels("1i") / 96, 1.0)  # 1.5 on a 150% display
        self.style = ttk.Style(root)
        self.theme_mode = tk.StringVar(value=theme_mode or theme.load_mode())
        self.palette = theme.resolve(self.theme_mode.get())
        self.panels: list[FindingsPanel] = []
        self._system_watch = None
        self._apply_styles()
        super().__init__(root, style="App.TFrame")
        root.title(f"Survey Cleaner {__version__}")
        root.minsize(int(860 * self.scale), int(620 * self.scale))
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # state
        self.data_paths: list[str] = []
        self.form_path = tk.StringVar()
        self.rules_path = tk.StringVar()
        self.data_label = tk.StringVar()
        self.survey = None
        self.form = None
        self.upload_findings: list = []
        self.res = None
        self.level_names: list[str] = []
        self.renames: dict[str, str] = {}
        self.keep: set[str] = set()
        self.labels: dict[str, str] = {}
        self.exported: Path | None = None

        self._build_header()
        body = ttk.Frame(self, style="App.TFrame", padding=(16, 10, 16, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.nb = ttk.Notebook(body)
        self.nb.grid(row=0, column=0, sticky="nsew")
        self.tabs = [ttk.Frame(self.nb, padding=16) for _ in range(4)]
        for t, title in zip(self.tabs, TAB_TITLES):
            self.nb.add(t, text=title)
        for i in (1, 2, 3):
            self.nb.tab(i, state="disabled")

        foot = ttk.Frame(self, style="App.TFrame", padding=(16, 8))
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(foot, mode="indeterminate", length=int(110 * self.scale))
        self.progress.grid(row=0, column=0, padx=(0, 10))
        self.status = autowrap(ttk.Label(foot, text="Step 1: choose your data export, or load the demo survey.",
                                         style="Status.TLabel", justify="left"))
        self.status.grid(row=0, column=1, sticky="ew")

        self._build_upload(self.tabs[0])
        self._build_reshape(self.tabs[1])
        self._build_preview(self.tabs[2])
        self._build_export(self.tabs[3])
        self._recolor()
        self._watch_system()

    # --- colours ---------------------------------------------------------------------
    def _apply_styles(self) -> None:
        theme.apply(self.root, self.style, self.palette, scale=self.scale)
        # Table rows tall enough for the font at any display scaling.
        linespace = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        self.style.configure("Treeview", rowheight=linespace + int(8 * self.scale))
        self.root.after_idle(lambda: theme.dark_title_bar(self.root, self.palette.name == "dark"))

    def _recolor(self) -> None:
        for panel in self.panels:
            panel.recolor(self.palette)

    def set_theme(self, mode: str | None = None, save: bool = True) -> None:
        if mode:
            self.theme_mode.set(mode)
        if save:
            theme.save_mode(self.theme_mode.get())
        self.palette = theme.resolve(self.theme_mode.get())
        self._apply_styles()
        self._recolor()

    def _watch_system(self) -> None:
        """In 'system' mode, follow Windows when the user switches light/dark."""
        def check():
            if self.theme_mode.get() == "system" and theme.resolve("system") != self.palette:
                self.set_theme(save=False)
            self._system_watch = self.root.after(4000, check)
        self._system_watch = self.root.after(4000, check)

    def destroy(self) -> None:
        if self._system_watch:
            try:
                self.root.after_cancel(self._system_watch)
            except tk.TclError:
                pass
        super().destroy()

    # --- header ------------------------------------------------------------------------
    def _build_header(self) -> None:
        bar = ttk.Frame(self, style="Header.TFrame", padding=(16, 10))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        try:
            icon = tk.PhotoImage(file=str(Path(str(resources.files("surveyclean") / "assets")) / "icon.png"))
            factor = max(1, round(icon.width() / (44 * self.scale)))
            self._logo = icon.subsample(factor)
            ttk.Label(bar, image=self._logo, style="HeaderIcon.TLabel").grid(row=0, column=0, rowspan=2,
                                                                             padx=(0, 12))
        except (tk.TclError, OSError):
            pass
        ttk.Label(bar, text="Survey Cleaner", style="HeaderTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(bar, text="Clean KoboToolbox & ODK exports  ·  one analysis-ready file",
                  style="HeaderSub.TLabel").grid(row=1, column=1, sticky="w")
        switch = ttk.Frame(bar, style="Header.TFrame")
        switch.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Label(switch, text="Theme", style="HeaderSub.TLabel").pack(side="left", padx=(0, 8))
        for value, text in (("light", "☀ Light"), ("dark", "☾ Dark"), ("system", "◐ System")):
            ttk.Radiobutton(switch, text=text, value=value, variable=self.theme_mode, style="Theme.TRadiobutton",
                            command=lambda: self.set_theme()).pack(side="left", padx=1)

    # --- helpers -------------------------------------------------------------------
    def set_status(self, text: str, error: bool = False) -> None:
        self.status.configure(text=text, style="StatusError.TLabel" if error else "Status.TLabel")

    def busy(self, on: bool) -> None:
        if on:
            self.progress.start(12)
        else:
            self.progress.stop()
        self.root.configure(cursor="watch" if on else "")

    def in_thread(self, work, done, message: str) -> None:
        """Run `work` in the background; hand its result to `done` on the window's
        own thread (Tkinter must only be touched from there)."""
        self.busy(True)
        self.set_status(message)
        results: queue.Queue = queue.Queue()

        def target():
            try:
                results.put(("ok", work()))
            except SurveyCleanError as exc:
                results.put(("error", (str(exc), "")))
            except Exception as exc:  # show anything unexpected instead of silently dying
                results.put(("error", (str(exc), traceback.format_exc())))

        def poll():
            try:
                kind, value = results.get_nowait()
            except queue.Empty:
                self.root.after(40, poll)
                return
            if kind == "ok":
                self.busy(False)
                done(value)
            else:
                self._failed(*value)

        threading.Thread(target=target, daemon=True).start()
        self.root.after(40, poll)

    def _failed(self, msg: str, tb: str) -> None:
        self.busy(False)
        text = msg if msg.startswith("Error") else f"Error: {msg}"
        self.set_status(text, error=True)
        messagebox.showerror("Survey Cleaner", text + (f"\n\nDetails:\n{tb[-1500:]}" if tb else ""))

    def go(self, index: int) -> None:
        for i in range(4):
            self.nb.tab(i, state="normal" if i <= index else "disabled")
        self.nb.select(index)
        if index == 3:
            self._update_export()

    def set_tab_count(self, index: int, findings) -> None:
        self.nb.tab(index, text=TAB_TITLES[index] + _count_label(findings))

    def _panel(self, parent, height: int = 7) -> FindingsPanel:
        panel = FindingsPanel(parent, height)
        self.panels.append(panel)
        panel.recolor(self.palette)
        return panel

    @staticmethod
    def _file_row(parent, row, label, var, command, clear=True):
        ttk.Label(parent, text=label, style="Strong.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        ttk.Entry(parent, textvariable=var, state="readonly").grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Button(parent, text="Browse…", command=command).grid(row=row, column=2, padx=(8, 0))
        if clear:
            ttk.Button(parent, text="Clear", command=lambda: var.set("")).grid(row=row, column=3, padx=(6, 0))

    # --- step 1: upload --------------------------------------------------------------
    def _build_upload(self, t):
        t.columnconfigure(1, weight=1)
        t.rowconfigure(7, weight=1)
        ttk.Label(t, text="Choose the files exported from KoboToolbox or ODK",
                  style="Heading.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        autowrap(ttk.Label(t, style="Muted.TLabel", justify="left", text=(
            "Data: Kobo's Excel export (repeat groups on extra sheets), a CSV export (repeat groups side by "
            "side are stacked automatically), or ODK Central's .zip. The XLSForm turns answer codes into labels "
            "(0 → No, 1 → Yes) and helps find problems. Rules are your own logic checks."))).grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(4, 16))
        self._file_row(t, 2, "Data export *", self.data_label, self.pick_data, clear=False)
        self._file_row(t, 3, "XLSForm (optional)", self.form_path,
                       lambda: self._pick(self.form_path, [("XLSForm", "*.xlsx *.xls")]))
        self._file_row(t, 4, "Rules (optional)", self.rules_path,
                       lambda: self._pick(self.rules_path, [("Rules", "*.yaml *.yml")]))
        self.upload_panel = self._panel(t)
        self.upload_panel.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        bar = ttk.Frame(t)
        bar.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        ttk.Button(bar, text="Load demo survey", command=self.load_demo).pack(side="left")
        self.next1 = ttk.Button(bar, text="Next: Reshape  ➜", style="Accent.TButton", command=self.analyse,
                                state="disabled")
        self.next1.pack(side="right")

    def _pick(self, var, types):
        chosen = filedialog.askopenfilename(filetypes=types + [("All files", "*.*")])
        if chosen:
            var.set(chosen)

    def pick_data(self):
        chosen = filedialog.askopenfilenames(filetypes=[("Survey exports", "*.xlsx *.xls *.csv *.zip"),
                                                        ("All files", "*.*")])
        if chosen:
            self.set_data(list(chosen))

    def set_data(self, paths: list[str]):
        self.data_paths = paths
        self.data_label.set("; ".join(Path(p).name for p in paths))
        self.next1.configure(state="normal" if paths else "disabled")
        self.set_status("Click 'Next: Reshape' to read and check the export.")

    def load_demo(self):
        d = demo_files()
        self.set_data([str(d["data"])])
        self.form_path.set(str(d["form"]))
        self.rules_path.set(str(d["rules"]))
        self.set_status("Demo loaded: a synthetic household survey with a household-member repeat group.")

    def analyse(self):
        if not self.data_paths:
            return
        paths, form_path = list(self.data_paths), self.form_path.get() or None

        def work():
            form = load_form_checked(form_path)
            survey = inspect(paths, form)
            return survey, form, check_upload(survey, form)
        self.in_thread(work, self._analysed, "Reading and checking the export…")

    # --- step 2: reshape -----------------------------------------------------------
    def _build_reshape(self, t):
        t.columnconfigure(0, weight=1)
        t.rowconfigure(5, weight=1)
        ttk.Label(t, text="Tables found in the export", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        self.tables_tree = ttk.Treeview(t, columns=("table", "parent", "rows", "cols"), show="headings", height=3)
        for col, text, w in [("table", "Table", 320), ("parent", "Linked to", 300), ("rows", "Rows", 80),
                             ("cols", "Columns", 80)]:
            self.tables_tree.heading(col, text=text)
            self.tables_tree.column(col, width=w, anchor="w" if col in ("table", "parent") else "e")
        self.tables_tree.grid(row=1, column=0, sticky="ew", pady=(8, 12))

        box = ttk.LabelFrame(t, text="One row per", padding=10)
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.level = ttk.Combobox(box, state="readonly")
        self.level.grid(row=0, column=0, sticky="ew")
        self.level.bind("<<ComboboxSelected>>", lambda e: self._explain_level())
        self.level_help = autowrap(ttk.Label(box, style="Muted.TLabel", justify="left"))
        self.level_help.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        opts = ttk.LabelFrame(t, text="Cleaning options", padding=10)
        opts.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.enum = tk.StringVar()
        self.outlier_k = tk.StringVar(value="3")
        ttk.Label(opts, text="Enumerator column").grid(row=0, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.enum, width=24).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(opts, text="(blank = detect automatically)", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Label(opts, text="Outlier strictness (IQR ×)").grid(row=0, column=3, sticky="w", padx=(24, 0))
        ttk.Spinbox(opts, from_=1, to=10, increment=0.5, textvariable=self.outlier_k, width=6).grid(
            row=0, column=4, sticky="w", padx=8)

        self.reshape_panel = self._panel(t)
        self.reshape_panel.grid(row=4, column=0, sticky="ew", pady=(14, 0))

        bar = ttk.Frame(t)
        bar.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(bar, text="◀  Back", command=lambda: self.nb.select(0)).pack(side="left")
        ttk.Button(bar, text="Next: Clean & preview  ➜", style="Accent.TButton", command=self.clean).pack(side="right")

    def _analysed(self, result):
        survey, form, upload_findings = result
        self.survey, self.form, self.upload_findings = survey, form, upload_findings
        self.upload_panel.show(upload_findings, "The files look fine.")
        self.set_tab_count(0, upload_findings)
        self.tables_tree.delete(*self.tables_tree.get_children())
        for info in survey.describe():
            self.tables_tree.insert("", "end", values=(
                info["name"], f"repeat group of {self._disp(info['parent'])}" if info["parent"]
                else "main table (submissions)", f"{info['rows']:,}", info["columns"]))
        self.tables_tree.configure(height=min(max(len(survey.tables), 2), 5))
        self.level_names = [survey.main] + [r.name for r in survey.repeats]
        labels = ["Submission (one row per submission)"]
        labels += [f"{r.name} — long format ({' → '.join(self._disp(p) for p in survey.path_to(r.name))})"
                   for r in survey.repeats]
        self.level.configure(values=labels)
        self.level.current(self.level_names.index(survey.default_level()))
        self._explain_level()
        self.go(1)
        n = len(survey.repeats)
        serious = sum(f.severity in ("problem", "warning") for f in upload_findings)
        found = f"Found the main table and {n} repeat group{'s' if n != 1 else ''}."
        checks = f" Step 1 checks: {serious} to look at (see 'Checks & suggestions')." if serious else ""
        self.set_status(found + checks + " Choose the row level.")

    def _disp(self, table: str) -> str:
        return "submission" if self.survey is not None and table == self.survey.main else f"'{table}'"

    def _explain_level(self):
        name = self.level_names[self.level.current()]
        if name == self.survey.main:
            extra = (" Each repeat group is summarised as a count column (n_<group>)."
                     if self.survey.repeats else "")
            self.level_help.configure(text="One row per submission." + extra)
        else:
            path = self.survey.path_to(name)
            self.level_help.configure(text=(
                f"Long format: one row per '{name}' record, with the answers of the "
                f"{' and '.join(self._disp(p) for p in path[:-1])} repeated on each of its rows. "
                "Submissions without any record are kept, with those columns empty. Submission-level "
                "checks still count each submission once."))
        reshape = check_reshape(self.survey, name, self.form)
        self.reshape_panel.show(None, "No problems found for this row level.", groups=[
            ("Your files (step 1)", [f for f in self.upload_findings if f.severity != "note"]),
            ("This row level", reshape)])
        self.set_tab_count(1, reshape)

    def clean(self):
        try:
            k = float(self.outlier_k.get())
        except ValueError:
            messagebox.showwarning("Survey Cleaner", "Outlier strictness must be a number, e.g. 3.")
            return
        level = self.level_names[self.level.current()]
        paths, form, rules = list(self.data_paths), self.form_path.get() or None, self.rules_path.get() or None
        enum = self.enum.get().strip() or None
        # Read the files again: cleaning changes the tables it is given.
        self.in_thread(lambda: run(paths, form=form, rules=rules, level=level,
                                   outlier_k=k, enumerator_col=enum),
                       self._cleaned, "Cleaning and checking…")

    # --- step 3: preview, choose & rename ------------------------------------------------
    def _build_preview(self, t):
        t.columnconfigure(0, weight=1)
        t.rowconfigure(4, weight=1)
        t.rowconfigure(7, weight=2)
        self.tiles = ttk.Frame(t)
        self.tiles.grid(row=0, column=0, sticky="ew")
        self.summary = autowrap(ttk.Label(t, style="Muted.TLabel", justify="left"))
        self.summary.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.preview_panel = self._panel(t)
        self.preview_panel.grid(row=2, column=0, sticky="ew", pady=(10, 6))
        self.use_labels = tk.BooleanVar(value=True)
        self.labels_check = ttk.Checkbutton(t, text="Replace answer codes with labels from the XLSForm (e.g. 1 → Yes)",
                                            variable=self.use_labels, command=self.refresh_preview)
        self.labels_check.grid(row=3, column=0, sticky="w", pady=(2, 6))

        pv = ttk.Frame(t)
        pv.grid(row=4, column=0, sticky="nsew")
        pv.columnconfigure(0, weight=1)
        pv.rowconfigure(0, weight=1)
        self.preview = ttk.Treeview(pv, show="headings", height=6)
        ys = ttk.Scrollbar(pv, orient="vertical", command=self.preview.yview)
        xs = ttk.Scrollbar(pv, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")

        choose = ttk.Frame(t)
        choose.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(choose, text="Variables to export:", style="Strong.TLabel").pack(side="left")
        self.keep_mode = tk.StringVar(value="all")
        ttk.Radiobutton(choose, text="All variables", value="all", variable=self.keep_mode,
                        command=self._mode_changed).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(choose, text="Selected variables only", value="selected", variable=self.keep_mode,
                        command=self._mode_changed).pack(side="left", padx=(10, 0))
        self.keep_count = ttk.Label(choose, style="Muted.TLabel")
        self.keep_count.pack(side="left", padx=(14, 0))

        self.rename_open = tk.BooleanVar(value=False)
        self.rename_toggle = ttk.Button(t, text="▸  Select & Rename Variables / Headers (optional)",
                                        command=self.toggle_rename)
        self.rename_toggle.grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.rename_box = ttk.Frame(t)
        self.rename_box.columnconfigure(0, weight=1)
        self.rename_box.rowconfigure(2, weight=1)
        tools = ttk.Frame(self.rename_box)
        tools.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(tools, text="Search").pack(side="left")
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add("write", lambda *_: self._fill_rename_tree())
        ttk.Entry(tools, textvariable=self.var_filter, width=24).pack(side="left", padx=(6, 12))
        ttk.Button(tools, text="Select all", command=lambda: self._select_all(True)).pack(side="left")
        ttk.Button(tools, text="Select none", command=lambda: self._select_all(False)).pack(side="left", padx=6)
        ttk.Button(tools, text="Reset names", command=self.reset_names).pack(side="left")
        autowrap(ttk.Label(self.rename_box, style="Muted.TLabel", justify="left", text=(
            "Click ☑/☐ to choose variables (this switches to 'Selected variables only'). Double-click "
            "'New Variable Name' to rename; Enter keeps it."))).grid(row=1, column=0, columnspan=2, sticky="ew",
                                                                     pady=(6, 0))
        self.rename_tree = ttk.Treeview(self.rename_box, columns=("keep", "orig", "label", "new"),
                                        show="headings", height=7)
        for col, text, w, anchor in [("keep", "Keep", 50, "center"), ("orig", "Original Variable Name", 190, "w"),
                                     ("label", "Label / Question Text", 400, "w"),
                                     ("new", "New Variable Name", 190, "w")]:
            self.rename_tree.heading(col, text=text)
            self.rename_tree.column(col, width=w, anchor=anchor, stretch=col == "label")
        rs = ttk.Scrollbar(self.rename_box, orient="vertical", command=self.rename_tree.yview)
        self.rename_tree.configure(yscrollcommand=rs.set)
        self.rename_tree.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        rs.grid(row=2, column=1, sticky="ns", pady=(4, 0))
        self.rename_tree.bind("<Button-1>", self._toggle_keep)
        self.rename_tree.bind("<Double-1>", self._edit_name)
        self.rename_msg = ttk.Label(self.rename_box, style="Error.TLabel")
        self.rename_msg.grid(row=3, column=0, sticky="w")

        bar = ttk.Frame(t)
        bar.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(bar, text="◀  Back", command=lambda: self.nb.select(1)).pack(side="left")
        ttk.Button(bar, text="Next: Name & export  ➜", style="Accent.TButton",
                   command=lambda: self.go(3)).pack(side="right")

    def _set_tiles(self, items) -> None:
        """Coloured number tiles: (value, label, kind) with kind '', 'warn' or 'bad'."""
        for w in self.tiles.winfo_children():
            w.destroy()
        for i, (value, label, kind) in enumerate(items):
            name = {"": "Tile", "warn": "TileWarn", "bad": "TileBad"}[kind]
            tile = ttk.Frame(self.tiles, style=f"{name}.TFrame", padding=(14, 6, 14, 8))
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            self.tiles.columnconfigure(i, weight=1, uniform="tiles")
            ttk.Label(tile, text=f"{value:,}", style=f"{name}Num.TLabel").pack(anchor="w")
            ttk.Label(tile, text=label, style=f"{name}Text.TLabel").pack(anchor="w")

    def _cleaned(self, res):
        self.res = res
        vt = variable_table(res)
        self.labels = dict(zip(vt["original"], vt["label"]))
        self.renames = {}
        self.keep = set(res.data.columns)
        self.keep_mode.set("all")
        self.var_filter.set("")
        has_labels = bool(res.form.choices)
        self.labels_check.configure(state="normal" if has_labels else "disabled")
        self.use_labels.set(has_labels)
        problems = sum(f.severity == "problem" for f in res.findings)
        self._set_tiles([
            (res.submissions, "submissions kept", ""),
            (len(res.data), f"rows (one per {res.level})" if len(res.level_path) > 1 else "rows", ""),
            (len(res.duplicates), "duplicates removed", "warn" if len(res.duplicates) else ""),
            (len(res.outliers), "possible outliers", "warn" if len(res.outliers) else ""),
            (len(res.rule_violations), "rule violations", "bad" if len(res.rule_violations) else ""),
            (problems, "problems to fix", "bad" if problems else ""),
        ])
        rows = f"one row per '{res.level}' record" if len(res.level_path) > 1 else "one row per submission"
        self.summary.configure(text=(f"{res.raw_shape[0]} submissions received  ·  {rows}  ·  "
                                     f"{len(res.data.columns)} variables  ·  "
                                     f"{sum(res.recoded_missing.values())} missing codes recoded"))
        preview_findings = [f for f in res.findings if f.step == "preview"]
        self.preview_panel.show(preview_findings, "The cleaned data look fine.")
        self.set_tab_count(2, preview_findings)
        self._fill_rename_tree()
        self.refresh_preview()
        self.go(2)
        self.set_status("Check the preview and the suggestions. Choosing and renaming variables is optional.")

    def selected(self) -> list[str] | None:
        """Variables to export; None means all."""
        if self.res is None or self.keep_mode.get() == "all":
            return None
        return [c for c in self.res.data.columns if c in self.keep]

    def _fill_rename_tree(self):
        if self.res is None:
            return
        needle = self.var_filter.get().strip().lower()
        all_mode = self.keep_mode.get() == "all"
        self.rename_tree.delete(*self.rename_tree.get_children())
        for c in self.res.data.columns:
            label = self.labels.get(c, "")
            if needle and needle not in c.lower() and needle not in label.lower():
                continue
            mark = "☑" if all_mode or c in self.keep else "☐"
            self.rename_tree.insert("", "end", iid=c, values=(mark, c, label, self.renames.get(c, c)))
        n = len(self.res.data.columns)
        k = n if all_mode else len([c for c in self.res.data.columns if c in self.keep])
        self.keep_count.configure(text=f"{k} of {n} selected", style="Error.TLabel" if k == 0 else "Muted.TLabel")

    def _mode_changed(self):
        if self.keep_mode.get() == "selected" and not self.rename_open.get():
            self.toggle_rename()
        self._fill_rename_tree()
        self.refresh_preview()

    def _select_all(self, on: bool):
        if self.res is None:
            return
        shown = set(self.rename_tree.get_children())
        if on:
            self.keep |= shown
        else:
            self.keep -= shown
        self.keep_mode.set("selected")
        self._fill_rename_tree()
        self.refresh_preview()

    def _toggle_keep(self, event):
        item = self.rename_tree.identify_row(event.y)
        if not item or self.rename_tree.identify_column(event.x) != "#1":
            return
        if self.keep_mode.get() == "all":  # first click: start from "everything ticked"
            self.keep = set(self.res.data.columns)
            self.keep_mode.set("selected")
        if item in self.keep:
            self.keep.discard(item)
        else:
            self.keep.add(item)
        self._fill_rename_tree()
        self.refresh_preview()
        return "break"

    def refresh_preview(self):
        if self.res is None:
            return
        keep = self.selected()
        if keep == []:
            self.preview.delete(*self.preview.get_children())
            self.preview.configure(columns=())
            self.rename_msg.configure(text="Choose at least one variable to export.")
            return
        try:
            df = prepare(self.res, "csv", self.renames, self.use_labels.get(), keep).data.head(60)
        except SurveyCleanError as exc:
            self.rename_msg.configure(text=str(exc))
            return
        self.rename_msg.configure(text="")
        cols = list(df.columns)
        self.preview.delete(*self.preview.get_children())
        self.preview.configure(columns=cols)
        for c in cols:
            self.preview.heading(c, text=c)
            self.preview.column(c, width=max(90, min(220, len(c) * 9)), stretch=False)
        for row in df.itertuples(index=False):
            self.preview.insert("", "end", values=["" if pd.isna(v) else str(v) for v in row])

    def toggle_rename(self):
        if self.rename_open.get():
            self.rename_box.grid_remove()
            self.preview.configure(height=6)
            self.rename_toggle.configure(text="▸  Select & Rename Variables / Headers (optional)")
        else:
            self.preview.configure(height=3)  # make room for the variable list
            self.rename_box.grid(row=7, column=0, sticky="nsew", pady=(4, 0))
            self.rename_toggle.configure(text="▾  Select & Rename Variables / Headers (optional)")
        self.rename_open.set(not self.rename_open.get())

    def _edit_name(self, event):
        item = self.rename_tree.identify_row(event.y)
        if not item or self.rename_tree.identify_column(event.x) != "#4":
            return
        x, y, w, h = self.rename_tree.bbox(item, "#4")
        var = tk.StringVar(value=self.rename_tree.set(item, "new"))
        entry = ttk.Entry(self.rename_tree, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, "end")

        def commit(_=None):
            if not entry.winfo_exists():  # Enter and focus-out both arrive
                return
            new = var.get().strip() or item
            entry.destroy()
            proposal = {**self.renames, item: new}
            proposal = {k: v for k, v in proposal.items() if v != k}
            taken = [proposal.get(c, c) for c in self.res.data.columns]
            if taken.count(new) > 1:
                self.rename_msg.configure(text=f"'{new}' is already used by another variable.")
                return
            self.rename_msg.configure(text="")
            self.renames = proposal
            self.rename_tree.set(item, "new", new)
            self.refresh_preview()
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def reset_names(self):
        self.renames = {}
        self.rename_msg.configure(text="")
        self._fill_rename_tree()
        self.refresh_preview()

    # --- step 4: name & export -------------------------------------------------------
    def _build_export(self, t):
        t.columnconfigure(1, weight=1)
        t.rowconfigure(7, weight=1)
        ttk.Label(t, text="Enter Output File Name *", style="Strong.TLabel").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar()
        self.name_entry = ttk.Entry(t, textvariable=self.name, font=("Segoe UI", 12))
        self.name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(12, 0))
        self.name_error = ttk.Label(t, text=NAME_REQUIRED, style="Error.TLabel")
        self.name_error.grid(row=1, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=(4, 10))

        ttk.Label(t, text="Format", style="Strong.TLabel").grid(row=2, column=0, sticky="nw", pady=(2, 0))
        fbox = ttk.Frame(t)
        fbox.grid(row=2, column=1, columnspan=2, sticky="w", padx=(12, 0))
        self.fmt = tk.StringVar(value="xlsx")
        for i, f in enumerate(FORMATS.values()):
            text = f.label if f.available else f"{f.label} — needs '{f.needs}'"
            ttk.Radiobutton(fbox, text=text, value=f.key, variable=self.fmt,
                            state="normal" if f.available else "disabled",
                            command=self._update_export).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 28), pady=3)
        self.fmt_help = autowrap(ttk.Label(t, style="Muted.TLabel", justify="left"))
        self.fmt_help.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=(6, 10))

        ttk.Label(t, text="Save in folder", style="Strong.TLabel").grid(row=4, column=0, sticky="w")
        self.folder = tk.StringVar(value=str(Path.home() / "Documents" / "Survey Cleaner exports"))
        ttk.Entry(t, textvariable=self.folder).grid(row=4, column=1, sticky="ew", padx=(12, 0))
        ttk.Button(t, text="Browse…", command=self._pick_folder).grid(row=4, column=2, padx=(8, 0))
        self.target = autowrap(ttk.Label(t, style="Muted.TLabel", justify="left"))
        self.target.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=(6, 4))

        self.export_panel = self._panel(t)
        self.export_panel.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        bar = ttk.Frame(t)
        bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Button(bar, text="◀  Back", command=lambda: self.nb.select(2)).pack(side="left")
        self.export_btn = ttk.Button(bar, text="Export 1 file", style="Accent.TButton", command=self.export,
                                     state="disabled")
        self.export_btn.pack(side="right")
        self.done = ttk.Frame(t)
        self.done.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.done_label = autowrap(ttk.Label(self.done, style="Success.TLabel", justify="left"), margin=4)
        self.done_label.pack(side="left", fill="x", expand=True)
        self.open_btn = ttk.Button(self.done, text="Open file", command=lambda: open_file(self.exported))
        self.folder_btn = ttk.Button(self.done, text="Open folder", command=lambda: open_file(self.exported.parent))

        self.name.trace_add("write", lambda *_: self._update_export())
        self.folder.trace_add("write", lambda *_: self._update_export())
        self._update_export()

    def _pick_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.folder.get() or None)
        if chosen:
            self.folder.set(chosen)

    def _update_export(self):
        f = FORMATS[self.fmt.get()]
        self.fmt_help.configure(text=FORMAT_HELP[f.key])
        if self.res is not None:
            keep = self.selected()
            findings = check_export(self.res, f.key, keep, self.renames)
            self.export_panel.show(findings, "Ready to export.")
            self.set_tab_count(3, findings)
            blocked = keep == [] or any(x.severity == "problem" for x in findings)
        else:
            blocked = True
        try:
            base = clean_filename(self.name.get())
        except SurveyCleanError:
            self.name_error.configure(text=NAME_REQUIRED)
            self.export_btn.configure(state="disabled")
            self.target.configure(text="")
            return
        self.name_error.configure(text="")
        self.export_btn.configure(state="disabled" if blocked else "normal")
        self.target.configure(text=f"Will be saved as: {Path(self.folder.get()) / (base + f.ext)}")

    def export(self):
        try:
            base = clean_filename(self.name.get())
        except SurveyCleanError as exc:
            self.name_error.configure(text=str(exc))
            self.export_btn.configure(state="disabled")
            return
        if base != self.name.get():
            self.name.set(base)  # show the name without the characters Windows does not allow
        f = FORMATS[self.fmt.get()]
        target = Path(self.folder.get()) / f"{base}{f.ext}"
        if target.exists() and not messagebox.askyesno(
                "Survey Cleaner", f"{target.name} already exists in this folder. Replace it?"):
            return
        res, folder, renames, labels = self.res, self.folder.get(), dict(self.renames), self.use_labels.get()
        keep = self.selected()
        self.in_thread(lambda: export_file(res, folder, base, f.key, rename=renames, use_labels=labels, keep=keep),
                       self._exported, f"Writing {target.name}…")

    def _exported(self, result):
        path, notes = result
        self.exported = path
        msg = f"✔ Saved 1 file: {path}"
        if notes:
            msg += "\n" + "\n".join(notes)
        self.done_label.configure(text=msg)
        self.open_btn.pack(side="right")
        self.folder_btn.pack(side="right", padx=8)
        self.set_status(f"Done. Saved {path.name}.")


def set_icon(root: tk.Tk) -> None:
    """Show the Survey Cleaner logo in the title bar and taskbar."""
    assets = Path(str(resources.files("surveyclean") / "assets"))
    try:
        if (assets / "icon.ico").exists() and sys.platform.startswith("win"):
            root.iconbitmap(default=str(assets / "icon.ico"))
        if (assets / "icon.png").exists():
            root._icon = tk.PhotoImage(file=str(assets / "icon.png"))  # keep a reference
            root.iconphoto(True, root._icon)
    except tk.TclError:
        pass  # an icon is nice to have, never a reason to fail


def main() -> None:
    if sys.platform.startswith("win"):
        try:  # own taskbar button and icon instead of Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("surveyclean.gui")
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled displays
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    scale = max(root.winfo_fpixels("1i") / 96, 1.0)
    w = min(int(1080 * scale), root.winfo_screenwidth() - 40)
    h = min(int(880 * scale), root.winfo_screenheight() - 80)
    root.geometry(f"{w}x{h}+{max((root.winfo_screenwidth() - w) // 2, 0)}+20")
    set_icon(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
