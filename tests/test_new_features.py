import pandas as pd
import pytest

from surveyclean import SurveyCleanError, clean, run
from surveyclean.cli import demo_files, main
from surveyclean.xlsform import Form, Question


def test_kobo_split_columns_named_after_question():
    df = pd.DataFrame({"lv/kept": ["cattle goats"], "lv/kept/cattle": ["1"],
                       "lv/kept/goats": ["1"], "lv/cattle": ["3"]})
    out, _ = clean.clean_column_names(df)
    # "lv/kept/cattle" must not collide with the real "cattle" question
    assert list(out.columns) == ["kept", "kept__cattle", "kept__goats", "cattle"]


def test_kobo_split_columns_rebuilt_without_duplicates():
    f = Form(questions={"kept": Question("kept", "select_multiple", "lv")},
             choices={"lv": {"cattle": "Cattle", "goats": "Goats"}})
    raw = pd.DataFrame({"lv/kept": ["cattle goats", "goats", None],
                        "lv/kept/cattle": ["True", "False", None],
                        "lv/kept/goats": ["1", "1", None], "_uuid": list("abc")})
    res = run(raw, form=f)
    assert list(res.data.columns).count("kept__cattle") == 1
    assert res.data["kept__cattle"].tolist()[:2] == [1, 0]


def test_numeric_missing_codes_with_decimals():
    df = pd.DataFrame({"age": ["-99.0", "34", "-88", " DK "]})
    out, counts = clean.recode_missing(df)
    assert counts == {"age": 3}
    assert out["age"].notna().tolist() == [False, True, False, False]


def test_datetimes_keep_local_offset_and_duration():
    f = Form(questions={"start": Question("start", "start"), "end": Question("end", "end")})
    df = pd.DataFrame({"start": ["2026-03-12T09:17:00.000+03:00", "2026-03-12T10:00:00+03:00"],
                       "end": ["2026-03-12T09:43:00.000+03:00", "2026-03-12T10:05:30+03:00"]})
    out, failures = clean.coerce_types(df, f)
    assert failures == {}
    assert out["start"].dt.hour.tolist() == [9, 10]  # local time, not UTC
    out = clean.add_duration(out)
    assert out["duration_min"].tolist() == [26.0, 5.5]


def test_enumerator_summary_counts_flags():
    df = pd.DataFrame({
        "enumerator": ["A", "A", "B", "B"], "x": [1, None, 3, 4],
        "duration_min": [30, 5, 40, 45], "_uuid": list("abcd")})
    violations = pd.DataFrame({"record": ["b"], "rule": ["r"], "detail": ["d"]})
    outliers = pd.DataFrame(columns=["record", "column", "value", "expected_range"])
    s = clean.enumerator_summary(df, "enumerator", outliers, violations).set_index("enumerator")
    assert s.loc["A", "submissions"] == 2
    assert s.loc["A", "missing_pct"] == 50.0
    assert s.loc["A", "under_10_min"] == 1
    assert s.loc["A", "rule_violations"] == 1 and s.loc["B", "rule_violations"] == 0
    assert s.index[0] == "A"  # most flags first


def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(SurveyCleanError, match="not found"):
        run(tmp_path / "nope.csv")


@pytest.mark.parametrize("name,content,message", [
    ("empty.csv", "", "empty"),
    ("rules.yaml", "rules: []\n", "not a survey export"),
    ("one_col.csv", "hello\nworld\n", "could not be read|does not look like"),
    ("one_row.csv", "a,b\n", "does not look like"),
])
def test_wrong_data_file_gives_clear_error(tmp_path, name, content, message):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    with pytest.raises(SurveyCleanError, match=message):
        run(f)


def test_bad_rules_file(tmp_path):
    data = tmp_path / "d.csv"
    data.write_text("a,_uuid\n1,x\n", encoding="utf-8")
    rules = tmp_path / "r.yaml"
    rules.write_text("rules:\n  - check: a > 0\n", encoding="utf-8")
    with pytest.raises(SurveyCleanError, match="name"):
        run(data, rules=rules)


def test_demo_end_to_end(tmp_path, capsys):
    assert all(p.exists() for p in demo_files().values())
    assert main(["--demo", "--name", "demo", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "124 in, 120 out (4 duplicates removed)" in out
    assert "one row per 'hh_members' record (725 rows)" in out
    assert "3 possible outliers, 10 rule violations" in out
    assert [p.name for p in tmp_path.iterdir()] == ["demo.xlsx"]  # exactly one file
    enum = pd.read_excel(tmp_path / "demo.xlsx", sheet_name="Data Quality Report", header=None)
    assert "Enumerator summary (by 'enumerator')" in enum[0].tolist()


def test_cli_error_exit_code(tmp_path, capsys):
    assert main([str(tmp_path / "missing.csv"), "--name", "x", "--out", str(tmp_path)]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_requires_a_name(tmp_path, capsys):
    assert main(["--demo", "--out", str(tmp_path)]) == 2
    assert "Error: Output file name is required before export." in capsys.readouterr().err
    assert not any(tmp_path.iterdir())
