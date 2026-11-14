"""Repeat groups stored side by side (one block of columns per record), as in
Kobo's single-sheet CSV export: they must become one row per record."""

import pandas as pd
import pytest

from surveyclean import export_file, inspect, run
from surveyclean.xlsform import Form, Question, Repeat

# Two FGDs; the participant block (consent, age, gender) is repeated 3 times.
# FGD a has 2 participants, FGD b has 3 (one declined consent).
WIDE_CSV = (
    "fgd_id,county,consent,age,gender,consent,age,gender,consent,age,gender,notes,_uuid\n"
    "1,2,1,33,2,1,38,1,,,,good,a\n"
    "2,1,1,51,1,0,,,1,40,2,,b\n"
)


@pytest.fixture
def wide_csv(tmp_path):
    p = tmp_path / "fgd.csv"
    p.write_text(WIDE_CSV, encoding="utf-8")
    return p


@pytest.fixture
def form():
    f = Form()
    f.questions = {
        "fgd_id": Question("fgd_id", "text", label="FGD ID"),
        "county": Question("county", "select_one", "county", "County"),
        "consent": Question("consent", "select_one", "yes_no", "Consent?", repeat="participants"),
        "age": Question("age", "integer", label="Age", repeat="participants"),
        "gender": Question("gender", "select_one", "gender", "Gender", repeat="participants"),
        "notes": Question("notes", "text", label="Notes"),
    }
    f.choices = {"county": {"1": "Busia", "2": "Kajiado"}, "yes_no": {"1": "Yes", "0": "No"},
                 "gender": {"1": "Male", "2": "Female"}}
    f.repeats = {"participants": Repeat("participants", "Participants")}
    return f


def test_side_by_side_block_is_stacked(wide_csv, form):
    s = inspect(wide_csv, form)
    assert [(t["name"], t["parent"], t["rows"]) for t in s.describe()] == [
        ("fgd", None, 2), ("participants", "fgd", 5)]  # empty 3rd slot of FGD a is not a record
    assert s.default_level() == "participants"
    assert "stored side by side" in s.notes[0]


def test_one_row_per_participant(wide_csv, form):
    res = run(wide_csv, form=form)
    d = res.data
    assert len(d) == 5
    assert d["_record"].tolist() == ["a/participants[1]", "a/participants[2]",
                                     "b/participants[1]", "b/participants[2]", "b/participants[3]"]
    assert d["age"].tolist()[:3] == [33, 38, 51]
    assert pd.isna(d.loc[3, "age"])  # declined consent: no other answers
    assert d["fgd_id"].tolist() == ["1", "1", "2", "2", "2"]  # group details on every row
    assert d["notes"].tolist()[0] == "good"
    assert not any(c.endswith(".1") or c.endswith(".2") for c in d.columns)


def test_without_xlsform_duplicated_headers_still_detected(wide_csv):
    s = inspect(wide_csv)
    assert [t["rows"] for t in s.describe()] == [2, 5]
    res = run(wide_csv)
    assert len(res.data) == 5 and "age" in res.data.columns


def test_indexed_headers(tmp_path):
    p = tmp_path / "hh.csv"
    p.write_text("village,members[1]/age,members[1]/sex,members[2]/age,members[2]/sex,_uuid\n"
                 "x,30,1,4,2,u1\n"
                 "y,61,2,,,u2\n", encoding="utf-8")
    s = inspect(p)
    assert [(t["name"], t["rows"]) for t in s.describe()] == [("hh", 2), ("members", 3)]
    d = run(p).data
    assert d["age"].tolist() == ["30", "4", "61"]  # no XLSForm: types are not guessed
    assert d["village"].tolist() == ["x", "x", "y"]


def test_labels_and_single_file_from_side_by_side(wide_csv, form, tmp_path):
    res = run(wide_csv, form=form)
    out = tmp_path / "out"
    path, _ = export_file(res, out, "FGD participants", "xlsx")
    assert [p.name for p in out.iterdir()] == ["FGD participants.xlsx"]
    d = pd.read_excel(path, sheet_name="FGD participants")
    assert len(d) == 5
    assert d["gender"].tolist()[:3] == ["Female", "Male", "Male"]
    assert d["consent"].tolist() == ["Yes", "Yes", "Yes", "No", "Yes"]
    assert d["county"].tolist()[0] == "Kajiado"


def test_plain_export_is_not_mistaken_for_repeats(tmp_path):
    p = tmp_path / "plain.csv"
    p.write_text("a,b,c,_uuid\n1,2,3,x\n4,5,6,y\n", encoding="utf-8")
    s = inspect(p)
    assert len(s.tables) == 1 and not s.notes
