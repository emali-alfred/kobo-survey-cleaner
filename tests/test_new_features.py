import pandas as pd
import pytest

from surveyclean import SurveyCleanError, clean, run, write_outputs
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
    assert s.loc["A", "records"] == 2
    assert s.loc["A", "missing_pct"] == 50.0
    assert s.loc["A", "under_10_min"] == 1
    assert s.loc["A", "rule_violations"] == 1 and s.loc["B", "rule_violations"] == 0
    assert s.index[0] == "A"  # most flags first


def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(SurveyCleanError, match="not found"):
        run(tmp_path / "nope.csv")


def test_bad_rules_file(tmp_path):
    data = tmp_path / "d.csv"
    data.write_text("a,_uuid\n1,x\n", encoding="utf-8")
    rules = tmp_path / "r.yaml"
    rules.write_text("rules:\n  - check: a > 0\n", encoding="utf-8")
    with pytest.raises(SurveyCleanError, match="name"):
        run(data, rules=rules)


def test_outputs_written(tmp_path, ):
    raw = pd.DataFrame({"q/n": ["1", "2", "3", "4", "5", "500"], "enumerator": list("aabbcc"),
                        "_uuid": list("uvwxyz")})
    res = run(raw)
    paths = write_outputs(res, tmp_path)
    for key in ["clean_csv", "report", "html", "excel", "enumerators"]:
        assert paths[key].exists(), key
    assert "<table>" in paths["html"].read_text(encoding="utf-8")
    sheets = pd.read_excel(paths["excel"], sheet_name=None)
    assert {"summary", "clean_data", "enumerators"} <= set(sheets)


def test_demo_end_to_end(tmp_path, capsys):
    assert all(p.exists() for p in demo_files().values())
    assert main(["--demo", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "124 in, 120 out (4 duplicates removed)" in out
    assert "3 possible outliers, 9 rule violations" in out
    enum = pd.read_csv(tmp_path / "enumerator_summary.csv")
    assert enum.loc[enum["enumerator"] == "enum_04", "under_10_min"].item() == 3


def test_cli_error_exit_code(tmp_path, capsys):
    assert main([str(tmp_path / "missing.csv"), "--out", str(tmp_path)]) == 2
    assert "not found" in capsys.readouterr().err
