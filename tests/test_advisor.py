"""Checks & suggestions at each step, and exporting selected variables only."""

import pandas as pd
import pytest

from surveyclean import SurveyCleanError, export_file, inspect, run
from surveyclean.advisor import check_export, check_reshape, check_upload
from surveyclean.cli import demo_files, main
from surveyclean.xlsform import Form, Question, Repeat


def titles(findings, severity=None):
    return [f.title for f in findings if severity is None or f.severity == severity]


@pytest.fixture(scope="module")
def demo():
    d = demo_files()
    return run(d["data"], form=d["form"], rules=d["rules"])


@pytest.fixture
def fgd(tmp_path):
    """Side-by-side participants with planted problems."""
    csv = ("fgd_id,consent,resp_id,resp_name,phone,age,gender,consent,resp_id,resp_name,phone,age,gender,"
           "consent,resp_id,resp_name,phone,age,gender,_uuid,_version\n"
           "1,1,1,Ann,0711,33,9,1,1,Bea,0712,38,1,0,,,,,,a,v1\n"     # code 1 twice; gender 9 not in form
           "1,1,4,Cid,0713,151,1,1,5,Dan,0714,40,2,,,,,,,b,v2\n")    # age 151; FGD 1 entered twice
    data = tmp_path / "fgd.csv"
    data.write_text(csv, encoding="utf-8")
    f = Form()
    f.questions = {
        "fgd_id": Question("fgd_id", "text", label="FGD ID"),
        "consent": Question("consent", "select_one", "yn", "Consent?", repeat="participants"),
        "resp_id": Question("resp_id", "integer", label="Respondent code", repeat="participants"),
        "resp_name": Question("resp_name", "text", label="Name", repeat="participants"),
        "phone": Question("phone", "text", label="Phone", repeat="participants"),
        "age": Question("age", "integer", label="Age", repeat="participants"),
        "gender": Question("gender", "select_one", "gender", "Gender", repeat="participants"),
        "products": Question("products", "select_multiple", "prod", "Products"),
    }
    f.choices = {"yn": {"1": "Yes", "0": "No"}, "gender": {"1": "Male", "2": "Female"},
                 "prod": {"1": "Acaricide", "-66": "-66"}}
    f.unlabelled = {"prod": ["-66"]}
    f.repeats = {"participants": Repeat("participants")}
    return data, f


# --- step 1 ---------------------------------------------------------------------------

def test_upload_checks(fgd):
    data, form = fgd
    s = inspect(data, form)
    f = check_upload(s, form)
    t = titles(f)
    assert "'gender': answer codes not in the XLSForm" in t
    assert "Choices list 'prod': option(s) without a label" in t
    assert "'fgd_id' repeats across submissions" in t
    assert "Data from 2 form versions" in t
    assert all(x.suggestion for x in f)  # every finding says what to do


def test_no_form_is_flagged(fgd):
    data, _ = fgd
    assert "No XLSForm added" in titles(check_upload(inspect(data)))


def test_wrong_form_is_a_problem(fgd):
    data, _ = fgd
    other = Form(questions={"x": Question("x", "text"), "y": Question("y", "integer")})
    assert "The XLSForm does not match this data" in titles(check_upload(inspect(data, other), other), "problem")


# --- step 2 ---------------------------------------------------------------------------

def test_reshape_checks(fgd):
    data, form = fgd
    s = inspect(data, form)
    f = check_reshape(s, "participants", form)
    assert "'resp_id' used twice within one submission" in titles(f, "problem")
    assert any("almost empty" in x for x in titles(f, "warning"))  # the declined consent


def test_household_level_suggests_repeat(fgd):
    data, form = fgd
    s = inspect(data, form)
    assert "Repeat groups are summarised, not listed" in titles(check_reshape(s, s.main, form))


# --- step 3 ---------------------------------------------------------------------------

def test_cleaned_checks_on_demo(demo):
    t = titles(demo.findings)
    assert "'hh_size': 1 answer(s) could not be read" in t  # 'twelve', counted once, not per member
    assert "'member_age': impossible ages" in t
    assert any("logic-check violation" in x for x in t)
    assert not any("exact copies" in x for x in t)  # 3-question member records are not 'copies'


def test_personal_data_flagged(fgd):
    data, form = fgd
    res = run(data, form=form)
    assert "The data contains personal information" in titles(res.findings)
    assert "'age': impossible ages" in titles(res.findings, "problem")


def test_findings_in_excel_report(tmp_path, demo):
    path, _ = export_file(demo, tmp_path, "x", "xlsx")
    sheet = pd.read_excel(path, sheet_name="Data Quality Report", header=None)
    col0 = sheet[0].astype(str).tolist()
    assert "Checks and suggestions" in col0
    assert "impossible ages" in " ".join(str(v) for v in sheet.values.ravel() if pd.notna(v))


# --- step 4 and selected variables ---------------------------------------------------

def test_export_checks(demo):
    f = check_export(demo, "dta", keep=["county", "member_age"])
    t = titles(f)
    assert "No row ID in the selection" in t
    assert "2 of 27 variables selected" in t or any("variables selected" in x for x in t)
    assert "No variables selected" in titles(check_export(demo, "csv", keep=[]), "problem")


def test_export_selected_variables_only(tmp_path, demo):
    keep = ["member_age", "_record", "county"]  # file keeps the data's order
    path, _ = export_file(demo, tmp_path, "sel", "csv", keep=keep)
    assert list(pd.read_csv(path).columns) == ["_record", "county", "member_age"]
    path, _ = export_file(demo, tmp_path, "all", "csv")
    assert len(pd.read_csv(path).columns) == len(demo.data.columns)
    with pytest.raises(SurveyCleanError, match="at least one variable"):
        export_file(demo, tmp_path, "none", "csv", keep=[])


def test_selected_variables_with_rename_and_labels(tmp_path, demo):
    path, _ = export_file(demo, tmp_path, "s", "dta", keep=["_record", "in_school"], rename={"in_school": "school"})
    with pd.io.stata.StataReader(path) as r:
        assert r.value_labels()["school"] == {0: "No", 1: "Yes"}
    assert list(pd.read_stata(path).columns) == ["_record", "school"]


def test_cli_keep_and_checks(tmp_path, capsys):
    assert main(["--demo", "--name", "k", "--format", "csv", "--keep", "_record", "member_age",
                 "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Checks & suggestions:" in out and "impossible ages" in out and "->" in out
    assert list(pd.read_csv(tmp_path / "k.csv").columns) == ["_record", "member_age"]
    assert main(["--demo", "--name", "k", "--keep", "nope", "--out", str(tmp_path)]) == 2
