"""Create a SYNTHETIC livestock household survey in KoboToolbox export format.

No real respondents: every value is randomly generated. Typical field-data
problems are injected on purpose so the cleaner has something to find:
duplicate submissions, -99 / "dk" codes, group-prefixed column names,
impossible values, logic inconsistencies, a text answer in a number field
and an extreme outlier.

Run:  python examples/make_sample_data.py
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
rng = np.random.default_rng(2026)
id_rng = np.random.default_rng(7)  # separate stream for submission IDs
N = 120

COUNTIES = {"1": "Kajiado", "2": "Narok", "3": "Makueni", "4": "Machakos", "5": "Isiolo"}
SEX = {"1": "Male", "2": "Female"}
LIVESTOCK = {"cattle": "Cattle", "goats": "Goats", "sheep": "Sheep", "poultry": "Poultry", "camels": "Camels"}
INCOME = {"crops": "Crop farming", "livestock": "Livestock", "business": "Small business",
          "wage": "Wage labour", "remittances": "Remittances"}
DECIDER = {"head": "Household head", "spouse": "Spouse", "joint": "Jointly", "other": "Other member"}
ENUMERATORS = ["enum_01", "enum_02", "enum_03", "enum_04", "enum_05"]


def submission_id() -> str:
    """A random version-4 UUID, like the _uuid Kobo gives each submission."""
    high = int(rng.integers(0, 2**63))
    low = int(id_rng.integers(0, 2**63))
    return str(uuid.UUID(int=(high << 64) | low, version=4))


def make_survey() -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2026-03-02 07:30", tz="Africa/Nairobi")
    for i in range(N):
        t0 = start + pd.Timedelta(days=int(rng.integers(0, 12)), minutes=int(rng.integers(0, 600)))
        t1 = t0 + pd.Timedelta(minutes=int(rng.integers(25, 70)))
        county = rng.choice(list(COUNTIES))
        cattle = int(rng.poisson(6)) if rng.random() < 0.8 else 0
        kept = [k for k, p in [("goats", .7), ("sheep", .4), ("poultry", .8), ("camels", .1)] if rng.random() < p]
        if cattle:
            kept.insert(0, "cattle")
        rows.append({
            "start": t0.isoformat(),
            "end": t1.isoformat(),
            "hh_info/county": county,
            "hh_info/hh_head_sex": rng.choice(["1", "2"], p=[.68, .32]),
            "hh_info/hh_head_age": int(np.clip(rng.normal(46, 12), 18, 90)),
            "hh_info/hh_size": int(rng.integers(1, 11)),
            "livestock/livestock_kept": " ".join(kept) if kept else None,
            "livestock/cattle_owned": cattle,
            "livestock/goats_owned": int(rng.poisson(9)) if "goats" in kept else 0,
            "livestock/cattle_sold_12m": int(rng.binomial(cattle, .2)) if cattle else 0,
            "livestock/milk_litres_day": round(float(rng.gamma(2, 2.5)), 1) if cattle else 0,
            "income/main_income": rng.choice(list(INCOME), p=[.3, .4, .15, .1, .05]),
            "income/monthly_income_kes": int(rng.lognormal(9.6, .55) // 100 * 100),
            "women/decides_livestock_sales": rng.choice(list(DECIDER), p=[.5, .15, .3, .05]),
            "_id": 400000 + i,
            "_uuid": submission_id(),
            "_submission_time": (t1 + pd.Timedelta(hours=3)).tz_convert(None).isoformat(),
            "_validation_status": "",
            "_status": "submitted_via_web",
            "__version__": "vXk3pQ7tLmN2",
            "formhub/uuid": "0f3c9b1e5a7d4c2b8e6f1a9d3c5b7e2f",
            "meta/instanceID": "",
            "_index": i + 1,
        })
    df = pd.DataFrame(rows)
    df["meta/instanceID"] = "uuid:" + df["_uuid"]
    df = df.astype(object)  # exports are text: allow "dk" in number columns

    # --- Inject realistic problems -------------------------------------------
    df.loc[[5, 41, 77], "hh_info/hh_head_age"] = -99            # "don't know" code
    df.loc[[12, 63], "income/monthly_income_kes"] = "dk"         # text missing code
    df.loc[90, "income/monthly_income_kes"] = -88                # refused
    df.loc[18, "hh_info/hh_head_age"] = 7                        # impossible age
    df.loc[[23, 58], "livestock/cattle_sold_12m"] = (
        df.loc[[23, 58], "livestock/cattle_owned"].astype(int) + 4)  # sold more than owned
    no_cattle = df.index[df["livestock/cattle_owned"] == 0][:2]
    df.loc[no_cattle, "livestock/milk_litres_day"] = 6.5         # milk with no cattle
    df.loc[34, "hh_info/hh_size"] = 0                            # empty household
    df.loc[47, "hh_info/hh_size"] = "twelve"                     # text in a number field
    df.loc[66, "income/monthly_income_kes"] = 2_500_000          # extreme outlier
    df.loc[101, "livestock/cattle_owned"] = 310                  # large herd: real or typo?

    # Enumerators (separate random stream so the other values stay the same).
    enum_rng = np.random.default_rng(11)
    df["enumerator"] = enum_rng.choice(ENUMERATORS, size=len(df))
    rushed = [9, 52, 88]                                         # one enumerator rushing
    df.loc[rushed, "enumerator"] = "enum_04"
    df.loc[rushed, "end"] = [
        (pd.Timestamp(s) + pd.Timedelta(minutes=m)).isoformat()
        for s, m in zip(df.loc[rushed, "start"], [6, 7, 8])]

    dupes = df.loc[[3, 29, 29, 84]].copy()                       # enumerator re-submitted
    df = pd.concat([df, dupes], ignore_index=True)
    df["_index"] = range(1, len(df) + 1)
    return df


MAIN_SHEET = "Livestock household survey"   # Kobo names the first sheet after the form
MEMBER_SHEET = "hh_members"


def make_members(main: pd.DataFrame) -> pd.DataFrame:
    """The household-member roster, a repeat group, as Kobo exports it: one row
    per member, linked to its household by _parent_index (the household's _index)."""
    rng_m = np.random.default_rng(31)  # own stream: household answers stay the same
    rows = []
    roster_of: dict[str, list[dict]] = {}
    for _, hh in main.iterrows():
        uuid_ = hh["_uuid"]
        if uuid_ not in roster_of:  # a re-submitted duplicate repeats the same roster
            size = int(hh["hh_info/hh_size"]) if str(hh["hh_info/hh_size"]).isdigit() else 4
            members = []
            for m in range(max(size, 0)):
                age = int(rng_m.integers(30, 80)) if m == 0 else int(rng_m.integers(0, 70))
                members.append({
                    "hh_members/member_sex": rng_m.choice(["1", "2"]),
                    "hh_members/member_age": age,
                    "hh_members/in_school": (rng_m.choice(["0", "1"], p=[.25, .75])
                                             if 6 <= age <= 17 else "0"),
                })
            roster_of[uuid_] = members
        for m in roster_of[uuid_]:
            rows.append({**m, "_parent_table_name": MAIN_SHEET, "_parent_index": hh["_index"],
                         "_submission__uuid": uuid_, "_submission__id": hh["_id"]})
    members = pd.DataFrame(rows).astype(object)
    members.insert(3, "_index", range(1, len(members) + 1))
    members.loc[7, "hh_members/member_age"] = 150                # impossible age
    members.loc[[15, 40], "hh_members/member_age"] = "dk"        # don't know
    return members


def make_form() -> dict[str, pd.DataFrame]:
    survey = pd.DataFrame([
        ("start", "start", ""),
        ("end", "end", ""),
        ("text", "enumerator", "Enumerator ID"),
        ("begin group", "hh_info", "Household information"),
        ("select_one county", "county", "County"),
        ("select_one sex", "hh_head_sex", "Sex of household head"),
        ("integer", "hh_head_age", "Age of household head (years)"),
        ("integer", "hh_size", "Number of household members"),
        ("end group", "", ""),
        ("begin repeat", "hh_members", "Household members"),
        ("select_one sex", "member_sex", "Sex of household member"),
        ("integer", "member_age", "Age of household member (years)"),
        ("select_one yesno", "in_school", "Is the member attending school?"),
        ("end repeat", "", ""),
        ("begin group", "livestock", "Livestock"),
        ("select_multiple livestock", "livestock_kept", "Which livestock does the household keep?"),
        ("integer", "cattle_owned", "Number of cattle owned"),
        ("integer", "goats_owned", "Number of goats owned"),
        ("integer", "cattle_sold_12m", "Cattle sold in the last 12 months"),
        ("decimal", "milk_litres_day", "Milk produced per day (litres)"),
        ("end group", "", ""),
        ("begin group", "income", "Income"),
        ("select_one income", "main_income", "Main source of income"),
        ("integer", "monthly_income_kes", "Household monthly income (KES)"),
        ("end group", "", ""),
        ("begin group", "women", "Decision making"),
        ("select_one decider", "decides_livestock_sales", "Who decides on livestock sales?"),
        ("end group", "", ""),
    ], columns=["type", "name", "label"])

    choices = pd.DataFrame(
        [("county", k, v) for k, v in COUNTIES.items()]
        + [("sex", k, v) for k, v in SEX.items()]
        + [("livestock", k, v) for k, v in LIVESTOCK.items()]
        + [("income", k, v) for k, v in INCOME.items()]
        + [("decider", k, v) for k, v in DECIDER.items()]
        + [("yesno", "0", "No"), ("yesno", "1", "Yes")],
        columns=["list_name", "name", "label"],
    )
    return {"survey": survey, "choices": choices}


if __name__ == "__main__":
    import shutil

    data = make_survey()
    members = make_members(data)
    # CSV export: the main table only (Kobo's CSV export has no repeat groups).
    data.to_csv(HERE / "sample_raw_export.csv", sep=";", index=False)  # Kobo's default separator
    # Excel export: main sheet + one sheet per repeat group, like Kobo's.
    with pd.ExcelWriter(HERE / "sample_raw_export.xlsx") as xw:
        data.to_excel(xw, sheet_name=MAIN_SHEET, index=False)
        members.to_excel(xw, sheet_name=MEMBER_SHEET, index=False)
    with pd.ExcelWriter(HERE / "sample_form.xlsx") as xw:
        for name, sheet in make_form().items():
            sheet.to_excel(xw, sheet_name=name, index=False)
    # Ship the same files inside the package for `surveyclean --demo` and the app.
    demo = HERE.parent / "surveyclean" / "demo"
    demo.mkdir(exist_ok=True)
    for f in ["sample_raw_export.xlsx", "sample_form.xlsx", "rules.yaml"]:
        shutil.copy(HERE / f, demo / f)
    (demo / "sample_raw_export.csv").unlink(missing_ok=True)
    print(f"Wrote {len(data)} synthetic households and {len(members)} members to "
          f"{HERE / 'sample_raw_export.xlsx'} (and the households alone to sample_raw_export.csv)")
    print(f"Wrote form definition to {HERE / 'sample_form.xlsx'}")
    print(f"Copied demo files to {demo}")
