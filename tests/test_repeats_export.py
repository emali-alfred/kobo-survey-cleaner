"""Repeat groups (long format), XLSForm labels, renaming and the single-file export."""

import zipfile

import pandas as pd
import pytest

from surveyclean import (NAME_REQUIRED, SurveyCleanError, clean_filename, export_file, inspect,
                         load_survey, reshape_long, run, variable_table)
from surveyclean.cli import demo_files
from surveyclean.export import FORMATS, prepare, valid_names
from surveyclean.xlsform import Form, Question, Repeat


# --- fixtures ------------------------------------------------------------------

@pytest.fixture
def kobo_xlsx(tmp_path):
    """A Kobo Excel export: households + members (repeat) + member illnesses (nested repeat)."""
    hh = pd.DataFrame({
        "hh/size": ["2", "1", "3", "2"],
        "hh/region": ["1", "2", "1", "1"],
        "_uuid": ["u1", "u2", "u3", "u1"],  # u1 submitted twice
        "_index": ["1", "2", "3", "4"],
    })
    members = pd.DataFrame({
        "members/age": ["40", "12", "-99", "30", "30"],
        "members/in_school": ["0", "1", "0", "0", "0"],
        "_index": ["1", "2", "3", "4", "5"],
        "_parent_table_name": ["HH survey"] * 5,
        "_parent_index": ["1", "1", "2", "4", "4"],  # 4 and 5 belong to the duplicate
        "_submission__uuid": ["u1", "u1", "u2", "u1", "u1"],
    })
    ill = pd.DataFrame({
        "illness/kind": ["flu", "malaria"],
        "_index": ["1", "2"],
        "_parent_table_name": ["members", "members"],
        "_parent_index": ["2", "2"],
    })
    path = tmp_path / "export.xlsx"
    with pd.ExcelWriter(path) as xw:
        hh.to_excel(xw, sheet_name="HH survey", index=False)
        members.to_excel(xw, sheet_name="members", index=False)
        ill.to_excel(xw, sheet_name="illness", index=False)
    return path


@pytest.fixture
def form():
    f = Form()
    f.questions = {
        "size": Question("size", "integer", label="Household size"),
        "region": Question("region", "select_one", "region", "Region"),
        "age": Question("age", "integer", label="Age", repeat="members"),
        "in_school": Question("in_school", "select_one", "yesno", "In school?", repeat="members"),
        "kind": Question("kind", "text", label="Illness", repeat="illness"),
    }
    f.choices = {"region": {"1": "North", "2": "South"}, "yesno": {"0": "No", "1": "Yes"}}
    f.repeats = {"members": Repeat("members", "Members"), "illness": Repeat("illness", parent="members")}
    return f


# --- repeat groups -----------------------------------------------------------------

def test_kobo_tables_detected(kobo_xlsx):
    s = inspect(kobo_xlsx)
    assert [(t["name"], t["parent"]) for t in s.describe()] == [
        ("HH survey", None), ("members", "HH survey"), ("illness", "members")]
    assert s.default_level() == "illness"  # deepest level of the first repeat group


def test_long_format_merges_children_to_parents(kobo_xlsx, form):
    res = run(kobo_xlsx, form=form, level="members")
    df = res.data
    assert len(res.duplicates) == 1
    # u1 has 2 members, u2 has 1, u3 has none but is kept; the duplicate's members are gone.
    assert df["_uuid"].tolist() == ["u1", "u1", "u2", "u3"]
    assert df["_record"].tolist() == ["u1/members[1]", "u1/members[2]", "u2/members[1]", "u3"]
    assert df["size"].tolist() == [2, 2, 1, 3]  # household answers repeated on member rows
    assert pd.isna(df.loc[2, "age"])  # -99 recoded
    assert df["n_illness"].tolist() == [0, 2, 0, 0]  # nested repeat off the path: counted


def test_nested_long_format(kobo_xlsx, form):
    res = run(kobo_xlsx, form=form, level="illness")
    assert res.level_path == ["HH survey", "members", "illness"]
    assert res.data["kind"].tolist() == [None, "flu", "malaria", None, None] or \
        res.data["kind"].isna().tolist() == [True, False, False, True, True]
    assert len(res.data) == 5


def test_household_checks_count_once_in_long_data(kobo_xlsx, form):
    rules = [{"name": "size_small", "check": "size < 3"}, {"name": "adult", "check": "age >= 18"}]
    res = run(kobo_xlsx, form=form, rules=rules, level="members")
    by_rule = res.rule_violations.groupby("rule")["record"].apply(list).to_dict()
    assert by_rule["size_small"] == ["u3"]  # once per submission, not per member
    assert by_rule["adult"] == ["u1/members[2]"]


def test_member_rules_skipped_at_household_level(kobo_xlsx, form):
    res = run(kobo_xlsx, form=form, rules=[{"name": "adult", "check": "age >= 18"}], level="HH survey")
    assert res.rule_violations.empty
    assert any("adult" in w and "repeat group" in w for w in res.warnings)
    assert res.data["n_members"].tolist() == [2, 1, 0]


def test_odk_central_zip(tmp_path):
    main = pd.DataFrame({"name": ["a", "b"], "KEY": ["uuid:1", "uuid:2"]})
    kids = pd.DataFrame({"kid_age": ["3", "5", "7"], "PARENT_KEY": ["uuid:1", "uuid:1", "uuid:2"],
                         "KEY": ["uuid:1/kids[1]", "uuid:1/kids[2]", "uuid:2/kids[1]"]})
    z = tmp_path / "odk.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("survey.csv", main.to_csv(index=False))
        zf.writestr("survey-kids.csv", kids.to_csv(index=False))
    s = load_survey(z)
    assert [t.parent for t in s.tables.values()] == [None, "survey"]
    df, id_col, _ = reshape_long(s, "survey-kids", id_col="KEY")
    assert df["kid_age"].tolist() == ["3", "5", "7"] and df["name"].tolist() == ["a", "a", "b"]


def test_unlinked_tables_are_refused(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("x,y\n1,2\n")
    b.write_text("p,q\n1,2\n")
    with pytest.raises(SurveyCleanError, match="not linked"):
        load_survey([a, b])


# --- file name -------------------------------------------------------------------------

@pytest.mark.parametrize("raw,clean", [
    ('Baseline: "round 1"?', "Baseline round 1"),
    ("a/b\\c*d<e>f|g", "abcdefg"),
    ("report.xlsx", "report"),
    ("  survey 2026 .  ", "survey 2026"),
    ("CON", "CON_"),
])
def test_clean_filename(raw, clean):
    assert clean_filename(raw) == clean


@pytest.mark.parametrize("raw", ["", "   ", '***', None, ".xlsx"])
def test_blank_filename_is_refused(raw):
    with pytest.raises(SurveyCleanError, match=NAME_REQUIRED):
        clean_filename(raw)


# --- export ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_res():
    d = demo_files()
    return run(d["data"], form=d["form"], rules=d["rules"])


@pytest.mark.parametrize("fmt", [f for f in FORMATS if FORMATS[f].available])
def test_each_format_writes_exactly_one_file(tmp_path, demo_res, fmt):
    path, _ = export_file(demo_res, tmp_path, "Baseline 2026", fmt)
    assert [p.name for p in tmp_path.iterdir()] == [f"Baseline 2026{FORMATS[fmt].ext}"]
    assert path.stat().st_size > 1000


def test_excel_has_four_sheets(tmp_path, demo_res):
    path, _ = export_file(demo_res, tmp_path, "Baseline 2026", "xlsx")
    sheets = pd.read_excel(path, sheet_name=None)
    assert list(sheets) == ["Baseline 2026", "Outliers", "Rule Violations", "Data Quality Report"]
    data = sheets["Baseline 2026"]
    assert len(data) == len(demo_res.data)
    assert set(data["in_school"].dropna()) <= {"No", "Yes"}  # codes labelled
    assert data["member_age"].isna().sum() == demo_res.data["member_age"].isna().sum()  # blank cells
    assert len(sheets["Rule Violations"]) == len(demo_res.rule_violations)


def test_csv_labels_and_blank_missing(tmp_path, demo_res):
    path, _ = export_file(demo_res, tmp_path, "x", "csv")
    text = path.read_text(encoding="utf-8-sig")
    df = pd.read_csv(path, keep_default_na=False)
    assert set(df["county"]) <= {"Kajiado", "Narok", "Makueni", "Machakos", "Isiolo"}
    assert "" in set(df["member_age"].astype(str))  # missing = empty cell
    assert "nan" not in text.lower().split(",") and "<NA>" not in text


def test_stata_value_labels_and_dot_missing(tmp_path, demo_res):
    path, notes = export_file(demo_res, tmp_path, "x", "dta")
    with pd.io.stata.StataReader(path) as r:
        vl = r.value_labels()
        labels = r.variable_labels()
    assert vl["in_school"] == {0: "No", 1: "Yes"}
    assert labels["member_age"] == "Age of household member (years)"
    codes = pd.read_stata(path, convert_categoricals=False)
    assert codes["member_age"].isna().sum() > 0  # Stata '.' reads back as missing
    assert "end_" in codes.columns and any("end" in n for n in notes)  # reserved word renamed


def test_spss_value_labels(tmp_path, demo_res):
    pyreadstat = pytest.importorskip("pyreadstat")
    path, _ = export_file(demo_res, tmp_path, "x", "sav")
    df, meta = pyreadstat.read_sav(str(path))
    assert meta.variable_value_labels["in_school"] == {0.0: "No", 1.0: "Yes"}
    assert meta.column_names_to_labels["member_age"] == "Age of household member (years)"
    assert df["member_age"].isna().sum() > 0


def test_r_factors_and_na(tmp_path, demo_res):
    pyreadr = pytest.importorskip("pyreadr")
    path, _ = export_file(demo_res, tmp_path, "x", "rds")
    df = pyreadr.read_r(str(path))[None]
    assert isinstance(df["county"].dtype, pd.CategoricalDtype)
    assert df["member_age"].isna().sum() > 0


def test_codes_kept_when_labels_off(tmp_path, demo_res):
    path, _ = export_file(demo_res, tmp_path, "x", "csv", use_labels=False)
    assert set(pd.read_csv(path)["in_school"].dropna().astype(int)) <= {0, 1}


def test_rename_variables(tmp_path, demo_res):
    path, _ = export_file(demo_res, tmp_path, "x", "csv", rename={"member_age": "age", "county": "district"})
    cols = pd.read_csv(path, nrows=1).columns
    assert "age" in cols and "district" in cols and "member_age" not in cols
    with pytest.raises(SurveyCleanError, match="same name"):
        export_file(demo_res, tmp_path, "y", "csv", rename={"member_age": "county"})


def test_variable_table_has_question_text(demo_res):
    t = variable_table(demo_res).set_index("original")["label"]
    assert t["member_age"] == "Age of household member (years)"
    assert t["livestock_kept__cattle"] == "Which livestock does the household keep?: Cattle"


def test_stata_and_spss_names_made_valid():
    assert valid_names(["1st", "a b", "end", "x" * 40], "dta") == ["v1st", "a_b", "end_", "x" * 32]
    assert valid_names(["_uuid", "with", "ok"], "sav") == ["vuuid", "with_", "ok"]


def test_prepare_does_not_change_the_cleaned_data(demo_res):
    before = demo_res.data.copy()
    prepare(demo_res, "dta", {"county": "district"})
    pd.testing.assert_frame_equal(before, demo_res.data)
