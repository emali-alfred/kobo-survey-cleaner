"""A small desktop window for people who prefer not to use the command line.

Start it with `surveyclean-gui` (or `python -m surveyclean.gui`)."""

from __future__ import annotations

import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .cli import demo_files, open_file
from .pipeline import SurveyCleanError, run
from .report import write_outputs


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=16)
        self.root = root
        root.title(f"Survey Cleaner {__version__}")
        root.minsize(720, 520)
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.data = tk.StringVar()
        self.form = tk.StringVar()
        self.rules = tk.StringVar()
        self.out = tk.StringVar(value=str(Path.home() / "Documents" / "surveyclean_output"))
        self.title_var = tk.StringVar(value="Data quality report")
        self.enum = tk.StringVar()
        self.outlier_k = tk.StringVar(value="3")
        self.paths: dict[str, Path] = {}

        ttk.Label(self, text="Clean a KoboToolbox / ODK export",
                  font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(self, text="Only the data file is required. Add the XLSForm for types, labels and "
                             "multi-select columns, and a rules file for logic checks.",
                  foreground="#555").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))

        types_data = [("Survey exports", "*.csv *.xlsx *.xls"), ("All files", "*.*")]
        self._file_row(2, "Data export *", self.data, types_data)
        self._file_row(3, "XLSForm", self.form, [("Excel", "*.xlsx *.xls"), ("All files", "*.*")])
        self._file_row(4, "Rules (YAML)", self.rules, [("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        self._file_row(5, "Output folder", self.out, None, folder=True)

        opts = ttk.Frame(self)
        opts.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text="Report title").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(opts, textvariable=self.title_var).grid(row=0, column=1, columnspan=3, sticky="ew")
        ttk.Label(opts, text="Enumerator column").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(opts, textvariable=self.enum, width=24).grid(row=1, column=1, sticky="w")
        ttk.Label(opts, text="(blank = auto-detect)", foreground="#777").grid(row=1, column=2, sticky="w")
        ttk.Label(opts, text="Outlier strictness (IQR ×)").grid(row=2, column=0, sticky="w", padx=(0, 8))
        ttk.Spinbox(opts, from_=1, to=10, increment=0.5, textvariable=self.outlier_k,
                    width=6).grid(row=2, column=1, sticky="w")

        btns = ttk.Frame(self)
        btns.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        self.run_btn = ttk.Button(btns, text="Clean data", command=self.start)
        self.run_btn.pack(side="left")
        ttk.Button(btns, text="Load demo survey", command=self.load_demo).pack(side="left", padx=8)
        self.report_btn = ttk.Button(btns, text="Open report", state="disabled",
                                     command=lambda: self._open("html"))
        self.report_btn.pack(side="right")
        self.excel_btn = ttk.Button(btns, text="Open Excel", state="disabled",
                                    command=lambda: self._open("excel"))
        self.excel_btn.pack(side="right", padx=8)
        self.folder_btn = ttk.Button(btns, text="Open folder", state="disabled",
                                     command=lambda: open_file(Path(self.out.get())))
        self.folder_btn.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.grid(row=8, column=0, columnspan=3, sticky="ew")
        self.log = tk.Text(self, height=12, wrap="word", font=("Consolas", 10), state="disabled")
        self.log.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        self.rowconfigure(9, weight=1)

    def _file_row(self, row, label, var, filetypes, folder=False):
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(self, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)

        def browse():
            if folder:
                chosen = filedialog.askdirectory(initialdir=var.get() or None)
            else:
                chosen = filedialog.askopenfilename(filetypes=filetypes)
            if chosen:
                var.set(chosen)
        ttk.Button(self, text="Browse…", command=browse).grid(row=row, column=2, padx=(8, 0), pady=3)

    def write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def load_demo(self) -> None:
        d = demo_files()
        self.data.set(str(d["data"]))
        self.form.set(str(d["form"]))
        self.rules.set(str(d["rules"]))
        self.out.set(str(Path.home() / "Documents" / "surveyclean_demo_output"))
        self.title_var.set("Livestock household survey: data quality report (synthetic demo)")
        self.write("Demo survey loaded (synthetic data, no real respondents). Click 'Clean data'.")

    def start(self) -> None:
        if not self.data.get().strip():
            messagebox.showwarning("Survey Cleaner", "Choose the data export to clean first.")
            return
        try:
            k = float(self.outlier_k.get())
        except ValueError:
            messagebox.showwarning("Survey Cleaner", "Outlier strictness must be a number, e.g. 3.")
            return
        self.run_btn.configure(state="disabled")
        for b in (self.report_btn, self.excel_btn, self.folder_btn):
            b.configure(state="disabled")
        self.progress.start(12)
        self.write(f"Cleaning {Path(self.data.get()).name} …")
        args = dict(data=self.data.get().strip(), form=self.form.get().strip() or None,
                    rules=self.rules.get().strip() or None, outlier_k=k,
                    enumerator_col=self.enum.get().strip() or None)
        threading.Thread(target=self._work, args=(args,), daemon=True).start()

    def _work(self, args: dict) -> None:
        try:
            res = run(**args)
            paths = write_outputs(res, self.out.get().strip(), self.title_var.get().strip()
                                  or "Data quality report")
        except SurveyCleanError as exc:
            self.root.after(0, self._failed, str(exc))
        except PermissionError as exc:
            self.root.after(0, self._failed, f"Cannot write {exc.filename}. Close it in Excel and try again.")
        except Exception as exc:  # show anything unexpected instead of silently dying
            self.root.after(0, self._failed, f"{exc}\n\n{traceback.format_exc()}")
        else:
            self.root.after(0, self._done, res, paths)

    def _failed(self, msg: str) -> None:
        self.progress.stop()
        self.run_btn.configure(state="normal")
        self.write("Error: " + msg)
        messagebox.showerror("Survey Cleaner", msg.split("\n\n")[0])

    def _done(self, res, paths: dict[str, Path]) -> None:
        self.progress.stop()
        self.run_btn.configure(state="normal")
        self.paths = paths
        for w in res.warnings:
            self.write("Warning: " + w)
        self.write(f"Records: {res.raw_shape[0]} in, {len(res.data)} out "
                   f"({len(res.duplicates)} duplicates removed)")
        self.write(f"Flags: {len(res.outliers)} possible outliers, "
                   f"{len(res.rule_violations)} rule violations")
        if res.enumerator_col:
            self.write(f"Enumerator summary by '{res.enumerator_col}' "
                       f"({len(res.enumerators)} enumerators)")
        self.write(f"Saved to {self.out.get()}")
        self.report_btn.configure(state="normal")
        self.folder_btn.configure(state="normal")
        if "excel" in paths:
            self.excel_btn.configure(state="normal")

    def _open(self, key: str) -> None:
        if key in self.paths:
            open_file(self.paths[key])


def set_icon(root: tk.Tk) -> None:
    """Show the Survey Cleaner logo in the title bar and taskbar."""
    from importlib import resources
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
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    set_icon(root)
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
