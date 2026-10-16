import pandas as pd
import pytest

from surveyclean import clean, run
from surveyclean.xlsform import Form, Question


@pytest.fixture
def form():
    f = Form()
    f.questions = {
        "age": Question("age", "integer"),
        "sex": Question("sex", "select_one", "sex"),
        "crops": Question("crops", "select_multiple", "crops"),
        "owned": Question("owned", "integer"),
        "sold": Question("sold", "integer"),
    }
    f.choices = {"sex": {"1": "Male", "2": "Female"},
                 "crops": {"maize": "Maize", "beans": "Beans"}}
    return f


@pytest.fixture
def raw():
    return pd.DataFrame({
        "grp/age": ["34", "-99", "51", "51", "twelve"],
        "grp/sex": ["1", "2", "1", "1", "2"],
        "farm/crops": ["maize beans", "beans", None, None, "maize"],
        "farm/owned": ["5", "3", "4", "4", "2"],
        "farm/sold": ["1", "6", "0", "0", "1"],
        "_uuid": ["a", "b", "c", "c", "d"],
        "__version__": ["v1"] * 5,
    })


def test_column_names_drop_group_prefix(raw):
    out, mapping = clean.clean_column_names(raw)
    assert list(out.columns[:5]) == ["age", "sex", "crops", "owned", "sold"]
    assert mapping["grp/age"] == "age"
    assert "_uuid" in out.columns


def test_name_clash_keeps_full_path():
    df = pd.DataFrame({"a/q1": [1], "b/q1": [2]})
    out, _ = clean.clean_column_names(df)
    assert list(out.columns) == ["a_q1", "b_q1"]


def test_duplicates_removed(raw):
    out, dropped = clean.remove_duplicates(raw)
    assert len(out) == 4 and len(dropped) == 1


def test_missing_codes_recoded(raw):
    out, counts = clean.recode_missing(raw)
    assert pd.isna(out.loc[1, "grp/age"])
    assert counts == {"grp/age": 1}


def test_type_coercion_reports_failures(raw, form):
    df, _ = clean.clean_column_names(raw)
    out, failures = clean.coerce_types(df, form)
    assert failures == {"age": 1}  # "twelve"
    assert pd.api.types.is_numeric_dtype(out["age"])


def test_select_multiple_split(raw, form):
    df, _ = clean.clean_column_names(raw)
    out, cols = clean.split_select_multiple(df, form)
    assert cols == ["crops__maize", "crops__beans"]
    assert out["crops__maize"].tolist()[:2] == [1, 0]
    assert pd.isna(out.loc[2, "crops__beans"])  # unanswered stays missing, not 0


def test_labels_added(raw, form):
    df, _ = clean.clean_column_names(raw)
    out, cols = clean.apply_labels(df, form)
    assert cols == ["sex_label"]
    assert out["sex_label"].tolist()[:2] == ["Male", "Female"]


def test_outliers_flagged_not_removed():
    df = pd.DataFrame({"cattle": [3, 4, 5, 4, 6, 5, 300], "_uuid": list("abcdefg")})
    flags = clean.flag_outliers(df)
    assert flags["record"].tolist() == ["g"]
    assert len(df) == 7


def test_rules_skip_missing_values():
    df = pd.DataFrame({"owned": [5, 2, None], "sold": [1, 6, 3], "_uuid": ["a", "b", "c"]})
    v = clean.check_rules(df, [{"name": "sold_le_owned", "check": "sold <= owned"}])
    assert v["record"].tolist() == ["b"]  # "c" is missing, not wrong


def test_bad_rule_is_reported_not_raised():
    df = pd.DataFrame({"x": [1]})
    v = clean.check_rules(df, [{"name": "broken", "check": "no_such_column > 1"}])
    assert "could not run" in v.loc[0, "detail"]


def test_full_pipeline(raw, form):
    rules = [{"name": "sold_le_owned", "check": "sold <= owned"}]
    res = run(raw, form=form, rules=rules)
    assert len(res.data) == 4
    assert "__version__" not in res.data.columns
    assert res.rule_violations["record"].tolist() == ["b"]
