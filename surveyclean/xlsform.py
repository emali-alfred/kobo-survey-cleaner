"""Read an XLSForm (the Excel form definition used by KoboToolbox and ODK)."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path

import pandas as pd


@dataclass
class Question:
    name: str
    qtype: str  # e.g. "integer", "select_one", "select_multiple", "text"
    list_name: str | None = None
    label: str | None = None


@dataclass
class Form:
    questions: dict[str, Question] = field(default_factory=dict)
    choices: dict[str, dict[str, str]] = field(default_factory=dict)  # list_name -> {value: label}

    def of_type(self, *types: str) -> list[Question]:
        return [q for q in self.questions.values() if q.qtype in types]

    def choice_labels(self, question: str) -> dict[str, str]:
        q = self.questions.get(question)
        if q is None or q.list_name is None:
            return {}
        return self.choices.get(q.list_name, {})


def _label_column(df: pd.DataFrame) -> str | None:
    """Pick the label column ("label" or the first "label::Language")."""
    for col in df.columns:
        if str(col).lower() == "label":
            return col
    for col in df.columns:
        if str(col).lower().startswith("label::"):
            return col
    return None


def load_form(path: str | Path) -> Form:
    """Parse the `survey` and `choices` sheets of an XLSForm."""
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    sheets = {k.lower(): v for k, v in sheets.items()}
    if "survey" not in sheets:
        raise ValueError(f"{path}: no 'survey' sheet found")

    form = Form()

    survey = sheets["survey"].dropna(subset=["type", "name"])
    s_label = _label_column(survey)
    for _, row in survey.iterrows():
        raw_type = str(row["type"]).strip()
        parts = raw_type.split()
        qtype = parts[0]
        list_name = parts[1] if len(parts) > 1 and qtype.startswith("select_") else None
        structural = raw_type.lower().replace("_", " ")
        if structural in {"begin group", "end group", "begin repeat", "end repeat"} or qtype == "note":
            continue
        label = row[s_label] if s_label and pd.notna(row[s_label]) else None
        name = re.sub(r"[^0-9a-zA-Z]+", "_", str(row["name"]).strip()).strip("_").lower()
        form.questions[name] = Question(name=name, qtype=qtype, list_name=list_name, label=label)

    if "choices" in sheets:
        choices = sheets["choices"].dropna(subset=["list_name", "name"])
        c_label = _label_column(choices)
        for _, row in choices.iterrows():
            lst = str(row["list_name"]).strip()
            value = str(row["name"]).strip()
            label = row[c_label] if c_label and pd.notna(row[c_label]) else value
            form.choices.setdefault(lst, {})[value] = str(label)

    return form
