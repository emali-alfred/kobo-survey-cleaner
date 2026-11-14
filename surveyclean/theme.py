"""Colours for the desktop window: light and dark palettes, 'system' mode that
follows the Windows setting, and the user's choice remembered between runs."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

MODES = ("system", "light", "dark")


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str           # window background
    surface: str      # cards / tab pages
    surface_alt: str  # inputs, tables, the checks box
    fg: str
    muted: str
    line: str
    brand: str        # teal of the logo
    brand_hover: str
    brand_fg: str     # text on brand
    brand_soft: str   # tinted tiles, selected rows
    header: str       # top bar
    header_fg: str
    accent: str       # amber of the logo
    problem: str
    warning: str
    note: str
    ok: str
    problem_soft: str
    warning_soft: str
    select: str       # selected row in tables


LIGHT = Palette(
    name="light", bg="#eef3f2", surface="#ffffff", surface_alt="#f7faf9", fg="#14232b", muted="#5b6b72",
    line="#d5e1de", brand="#0f7a68", brand_hover="#0b6253", brand_fg="#ffffff", brand_soft="#e1f3ec",
    header="#0d6b5c", header_fg="#ffffff", accent="#f5a524", problem="#c62828", warning="#a15c00",
    note="#1f6aa5", ok="#13804a", problem_soft="#fde8e7", warning_soft="#fff3dc", select="#c9ebdf",
)

DARK = Palette(
    name="dark", bg="#0d1417", surface="#152126", surface_alt="#1b2a30", fg="#e4eef0", muted="#97a9ae",
    line="#2a3b42", brand="#2fbf96", brand_hover="#4fd4ad", brand_fg="#06231b", brand_soft="#173a33",
    header="#10322b", header_fg="#e9fbf5", accent="#f5b544", problem="#ff7a6e", warning="#f4b740",
    note="#6cb6ff", ok="#4cd391", problem_soft="#3b1f1f", warning_soft="#3a2f12", select="#1f4a40",
)


def system_prefers_dark() -> bool:
    """Windows 'Choose your app mode'; light elsewhere or when unknown."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


def resolve(mode: str) -> Palette:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    return DARK if system_prefers_dark() else LIGHT


# --- remembered choice ------------------------------------------------------------------

def settings_file() -> Path:
    base = os.environ.get("SURVEYCLEAN_SETTINGS_DIR") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "SurveyCleaner" / "settings.json"


def load_mode() -> str:
    try:
        mode = json.loads(settings_file().read_text(encoding="utf-8")).get("theme", "system")
    except (OSError, ValueError, AttributeError):
        return "system"
    return mode if mode in MODES else "system"


def save_mode(mode: str) -> None:
    path = settings_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    data["theme"] = mode
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # a remembered theme is a convenience, never a reason to fail


# --- applying it to Tk ---------------------------------------------------------------------

def dark_title_bar(window, on: bool) -> None:
    """Windows 10/11: match the title bar to the theme."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if on else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


def apply(root, style, p: Palette, font: str = "Segoe UI", scale: float = 1.0) -> None:
    """Style every ttk widget class the window uses. Built on the 'clam' theme,
    the one ttk theme whose colours can all be changed."""
    style.theme_use("clam")
    root.configure(background=p.bg)
    base = (font, 10)
    style.configure(".", background=p.surface, foreground=p.fg, fieldbackground=p.surface_alt,
                    bordercolor=p.line, lightcolor=p.surface, darkcolor=p.surface, troughcolor=p.surface_alt,
                    focuscolor=p.brand, selectbackground=p.select, selectforeground=p.fg,
                    insertcolor=p.fg, font=base)
    style.configure("TFrame", background=p.surface)
    style.configure("App.TFrame", background=p.bg)
    style.configure("Header.TFrame", background=p.header)
    style.configure("Tile.TFrame", background=p.brand_soft, relief="flat")
    style.configure("TileWarn.TFrame", background=p.warning_soft)
    style.configure("TileBad.TFrame", background=p.problem_soft)
    style.configure("Checks.TFrame", background=p.surface_alt, bordercolor=p.line, relief="solid", borderwidth=1)
    style.configure("ChecksInner.TFrame", background=p.surface_alt, relief="flat", borderwidth=0)

    style.configure("TLabel", background=p.surface, foreground=p.fg)
    style.configure("Muted.TLabel", foreground=p.muted)
    style.configure("Error.TLabel", foreground=p.problem)
    style.configure("Success.TLabel", foreground=p.ok)
    style.configure("Heading.TLabel", font=(font, 12, "bold"))
    style.configure("Strong.TLabel", font=(font, 10, "bold"))
    style.configure("Status.TLabel", background=p.bg, foreground=p.muted)
    style.configure("StatusError.TLabel", background=p.bg, foreground=p.problem)
    style.configure("HeaderTitle.TLabel", background=p.header, foreground=p.header_fg, font=(font, 17, "bold"))
    style.configure("HeaderSub.TLabel", background=p.header, foreground=p.header_fg, font=(font, 10))
    style.configure("HeaderIcon.TLabel", background=p.header)
    for tile, bgc, numc in (("Tile", p.brand_soft, p.brand), ("TileWarn", p.warning_soft, p.warning),
                            ("TileBad", p.problem_soft, p.problem)):
        style.configure(f"{tile}Num.TLabel", background=bgc, foreground=numc, font=(font, 18, "bold"))
        style.configure(f"{tile}Text.TLabel", background=bgc, foreground=p.muted, font=(font, 9))
    style.configure("Checks.TLabel", background=p.surface_alt, foreground=p.fg, font=(font, 10, "bold"))
    for sev, colour in (("Problem", p.problem), ("Warning", p.warning), ("Note", p.note), ("Ok", p.ok)):
        style.configure(f"Chip{sev}.TLabel", background=p.surface_alt, foreground=colour, font=(font, 10, "bold"))

    # Buttons: quiet by default, filled teal for the main action of each step.
    style.configure("TButton", background=p.surface_alt, foreground=p.fg, bordercolor=p.line,
                    lightcolor=p.surface_alt, darkcolor=p.surface_alt, padding=(12, 6), relief="solid",
                    borderwidth=1)
    style.map("TButton", background=[("disabled", p.surface), ("pressed", p.brand_soft), ("active", p.brand_soft)],
              foreground=[("disabled", p.muted)], bordercolor=[("focus", p.brand), ("active", p.brand)])
    style.configure("Accent.TButton", background=p.brand, foreground=p.brand_fg, bordercolor=p.brand,
                    lightcolor=p.brand, darkcolor=p.brand, padding=(16, 7), font=(font, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", p.line), ("pressed", p.brand_hover), ("active", p.brand_hover)],
              foreground=[("disabled", p.muted)], lightcolor=[("active", p.brand_hover)],
              darkcolor=[("active", p.brand_hover)])
    style.configure("Link.TButton", background=p.surface_alt, foreground=p.brand, borderwidth=0,
                    lightcolor=p.surface_alt, darkcolor=p.surface_alt, padding=(6, 2), font=(font, 9, "bold"))
    style.map("Link.TButton", background=[("active", p.brand_soft)])
    style.configure("Theme.TRadiobutton", background=p.header, foreground=p.header_fg, indicatorsize=0,
                    padding=(10, 4), font=(font, 9))
    style.map("Theme.TRadiobutton", background=[("selected", p.brand), ("active", p.brand_hover)],
              foreground=[("selected", p.brand_fg)])

    # Inputs.
    for widget in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(widget, fieldbackground=p.surface_alt, foreground=p.fg, bordercolor=p.line,
                        lightcolor=p.surface_alt, darkcolor=p.surface_alt, arrowcolor=p.muted, padding=4)
        style.map(widget, bordercolor=[("focus", p.brand)], lightcolor=[("focus", p.brand)],
                  fieldbackground=[("readonly", p.surface_alt), ("disabled", p.surface)],
                  foreground=[("disabled", p.muted)], selectbackground=[("readonly", p.surface_alt)],
                  selectforeground=[("readonly", p.fg)])
    root.option_add("*TCombobox*Listbox.background", p.surface_alt)
    root.option_add("*TCombobox*Listbox.foreground", p.fg)
    root.option_add("*TCombobox*Listbox.selectBackground", p.select)
    root.option_add("*TCombobox*Listbox.selectForeground", p.fg)
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(widget, background=p.surface, foreground=p.fg, indicatorbackground=p.surface_alt,
                        indicatorforeground=p.brand_fg, indicatormargin=(0, 0, int(6 * scale), 0),
                        indicatorsize=int(13 * scale), upperbordercolor=p.muted, lowerbordercolor=p.muted)
        style.map(widget, foreground=[("disabled", p.muted)], background=[("active", p.surface)],
                  upperbordercolor=[("selected", p.brand), ("active", p.brand)],
                  lowerbordercolor=[("selected", p.brand), ("active", p.brand)])
    # Tick box: filled teal with a light tick. Round button: teal dot in a teal ring.
    style.map("TCheckbutton", indicatorbackground=[("selected", p.brand), ("disabled", p.surface)],
              indicatorforeground=[("selected", p.brand_fg)])
    style.map("TRadiobutton", indicatorbackground=[("disabled", p.surface)],
              indicatorforeground=[("selected", p.brand), ("!selected", p.surface_alt)])

    # Tabs: flat, with the current step in teal.
    style.configure("TNotebook", background=p.bg, borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=p.bg, foreground=p.muted, padding=(16, 8), borderwidth=0,
                    lightcolor=p.bg, bordercolor=p.bg, font=(font, 10, "bold"))
    style.map("TNotebook.Tab", background=[("selected", p.surface), ("active", p.brand_soft)],
              foreground=[("selected", p.brand), ("disabled", p.line)],
              lightcolor=[("selected", p.brand)], expand=[("selected", (0, 2, 0, 0))])

    # Tables.
    style.configure("Treeview", background=p.surface_alt, fieldbackground=p.surface_alt, foreground=p.fg,
                    bordercolor=p.line, lightcolor=p.surface_alt, darkcolor=p.surface_alt)
    style.map("Treeview", background=[("selected", p.select)], foreground=[("selected", p.fg)])
    style.configure("Treeview.Heading", background=p.brand_soft, foreground=p.fg, bordercolor=p.line,
                    lightcolor=p.brand_soft, darkcolor=p.brand_soft, relief="flat", font=(font, 9, "bold"))
    style.map("Treeview.Heading", background=[("active", p.select)])

    style.configure("TLabelframe", background=p.surface, bordercolor=p.line, lightcolor=p.surface,
                    darkcolor=p.surface)
    style.configure("TLabelframe.Label", background=p.surface, foreground=p.brand, font=(font, 10, "bold"))
    style.configure("TScrollbar", background=p.line, troughcolor=p.surface_alt, bordercolor=p.surface_alt,
                    arrowcolor=p.muted, lightcolor=p.line, darkcolor=p.line, gripcount=0)
    style.map("TScrollbar", background=[("active", p.muted)])
    style.configure("Horizontal.TProgressbar", background=p.brand, troughcolor=p.surface_alt, bordercolor=p.bg,
                    lightcolor=p.brand, darkcolor=p.brand)
    style.configure("TSeparator", background=p.line)
