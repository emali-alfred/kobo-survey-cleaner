"""Walk through the four-step desktop window with the demo survey."""

import time

import pandas as pd
import pytest

tk = pytest.importorskip("tkinter")


def _wait(root, condition, timeout=60):
    end = time.time() + timeout
    while not condition():
        root.update()
        if time.time() > end:
            raise TimeoutError("the window did not finish in time")
        time.sleep(0.02)


@pytest.fixture(scope="module")
def tk_root():
    # One Tk per test module: creating several in one process is unreliable on Windows.
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display ({exc})")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root):
    from surveyclean.gui import App
    window = tk.Toplevel(tk_root)
    window.withdraw()
    a = App(window)
    yield a
    window.destroy()


def test_wizard_exports_one_named_file(app, tmp_path):
    # Steps 2-4 are locked until the earlier steps are done.
    assert [app.nb.tab(i, "state") for i in range(4)] == ["normal", "disabled", "disabled", "disabled"]

    # 1 Upload
    app.load_demo()
    app.analyse()
    _wait(app.root, lambda: app.survey is not None)
    assert app.nb.index("current") == 1
    assert app.level_names == ["Livestock household survey", "hh_members"]
    assert app.level.get().startswith("hh_members")  # long format by default

    # 2 Reshape
    app.clean()
    _wait(app.root, lambda: app.res is not None)
    assert app.nb.index("current") == 2
    assert len(app.res.data) == 725

    # 3 Preview & Rename (optional)
    assert len(app.rename_tree.get_children()) == len(app.res.data.columns)
    app.toggle_rename()
    app.renames = {"member_age": "age"}
    app.refresh_preview()
    assert "age" in app.preview["columns"] and "member_age" not in app.preview["columns"]
    first = app.preview.item(app.preview.get_children()[0], "values")
    assert "Machakos" in first  # labels, not codes

    # 4 Name & Export: blank name -> error shown, export disabled
    app.go(3)
    app.name.set("   ")
    assert str(app.export_btn["state"]) == "disabled"
    assert app.name_error["text"] == "Error: Output file name is required before export."

    app.folder.set(str(tmp_path))
    app.fmt.set("xlsx")
    app.name.set('Baseline: "round 1"?')
    assert str(app.export_btn["state"]) == "normal" and app.name_error["text"] == ""
    app.export()
    _wait(app.root, lambda: app.exported is not None)
    assert app.name.get() == "Baseline round 1"  # illegal characters stripped on submit
    assert [p.name for p in tmp_path.iterdir()] == ["Baseline round 1.xlsx"]
    sheets = pd.read_excel(app.exported, sheet_name=None)
    assert list(sheets) == ["Baseline round 1", "Outliers", "Rule Violations", "Data Quality Report"]
    assert "age" in sheets["Baseline round 1"].columns


def _panel_text(panel):
    return panel.text.get("1.0", "end")


def test_checks_shown_and_selected_variables_only(app, tmp_path):
    app.load_demo()
    app.analyse()
    _wait(app.root, lambda: app.survey is not None)
    # Step 1 and 2 checks: duplicates found in the files, shown with a count on the tab.
    assert "duplicate submission" in _panel_text(app.upload_panel)
    assert "⚠" in app.nb.tab(0, "text")
    assert "your files (step 1)" in _panel_text(app.reshape_panel).lower()

    app.clean()
    _wait(app.root, lambda: app.res is not None)
    text = _panel_text(app.preview_panel)
    assert "impossible ages" in text and "could not be read" in text
    assert "→" in text  # every finding comes with a suggestion

    # Choose 3 variables only.
    app.keep_mode.set("selected")
    app.keep = {"_record", "county", "member_age"}
    app._mode_changed()
    assert list(app.preview["columns"]) == ["_record", "county", "member_age"]
    assert app.keep_count["text"] == f"3 of {len(app.res.data.columns)} selected"

    app.go(3)
    app.folder.set(str(tmp_path))
    app.fmt.set("csv")
    app.name.set("three vars")
    app._update_export()
    assert "3 of" in _panel_text(app.export_panel)
    app.export()
    _wait(app.root, lambda: app.exported is not None)
    assert list(pd.read_csv(app.exported).columns) == ["_record", "county", "member_age"]

    # Nothing selected: export is blocked with a clear message.
    app.keep = set()
    app._mode_changed()
    app._update_export()
    assert str(app.export_btn["state"]) == "disabled"
    assert "No variables selected" in _panel_text(app.export_panel)


@pytest.fixture(autouse=True)
def fail_on_tk_callback_errors(monkeypatch):
    """Tk only prints errors raised inside callbacks; make them fail the test."""
    errors = []
    monkeypatch.setattr(tk.Tk, "report_callback_exception", lambda self, *exc: errors.append(exc))
    yield
    assert not errors, errors


def test_theme_switch_and_compact_checks(app, tmp_path, monkeypatch):
    from surveyclean import theme
    monkeypatch.setenv("SURVEYCLEAN_SETTINGS_DIR", str(tmp_path))
    style = app.style
    app.set_theme("dark")
    assert app.palette is theme.DARK
    assert style.lookup("TFrame", "background") == theme.DARK.surface
    assert app.upload_panel.text.cget("background") == theme.DARK.surface_alt
    assert theme.load_mode() == "dark"  # remembered for next time
    app.set_theme("light")
    assert style.lookup("Accent.TButton", "background") == theme.LIGHT.brand
    app.set_theme("system")
    assert app.palette in (theme.LIGHT, theme.DARK) and theme.load_mode() == "system"

    # The checks bar is compact: details stay hidden until asked for.
    app.load_demo()
    app.analyse()
    _wait(app.root, lambda: app.survey is not None)
    panel = app.upload_panel
    assert not panel.body.winfo_ismapped() and not panel.open
    chips = [w.cget("text") for w in panel.chips.winfo_children()]
    assert any("warning" in c for c in chips)
    panel.toggle()
    assert panel.open and panel.toggle_btn.cget("text").startswith("Hide")
