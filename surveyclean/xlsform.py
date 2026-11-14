"""Read an XLSForm (the Excel form definition used by KoboToolbox and ODK)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


def snake(name: str) -> str:
    """The column-name style used after cleaning ("Member Age" -> "member_age")."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip()).strip("_").lower()


def code_key(value) -> str:
    """Normalise an answer code so "1", 1, 1.0 and " 1 " all match the choice "1"."""
    text = str(value).strip()
    if re.fullmatch(r"-?\d+\.0+", text):
        text = text.split(".")[0]
    return text


@dataclass
class Question:
    name: str
    qtype: str  # e.g. "integer", "select_one", "select_multiple", "text"
    list_name: str | None = None
    label: str | None = None
    repeat: str | None = None  # innermost repeat group the question sits in
    relevant: str | None = None  # skip logic: own and enclosing groups' conditions
    required: bool = False


@dataclass
class Repeat:
    name: str
    label: str | None = None
    parent: str | None = None  # enclosing repeat group, None for the main table


@dataclass
class Form:
    questions: dict[str, Question] = field(default_factory=dict)
    choices: dict[str, dict[str, str]] = field(default_factory=dict)  # list_name -> {code: label}
    repeats: dict[str, Repeat] = field(default_factory=dict)
    unlabelled: dict[str, list[str]] = field(default_factory=dict)  # list_name -> codes without a label
    title: str | None = None

    def of_type(self, *types: str) -> list[Question]:
        return [q for q in self.questions.values() if q.qtype in types]

    def choice_labels(self, question: str) -> dict[str, str]:
        q = self.questions.get(question)
        if q is None or q.list_name is None:
            return {}
        return self.choices.get(q.list_name, {})

    def label(self, column: str) -> str | None:
        """Question text for a cleaned column name, including split multi-select
        columns ("crops__maize" -> "Crops grown: Maize")."""
        q = self.questions.get(column)
        if q is not None:
            return q.label
        if "__" in column:
            base, _, opt = column.partition("__")
            q = self.questions.get(base)
            if q is not None:
                opt_label = self.choice_labels(base).get(opt, opt)
                return f"{q.label or base}: {opt_label}"
        return None


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
    sheets = {k.strip().lower(): v for k, v in sheets.items()}
    if "survey" not in sheets:
        raise ValueError(f"{Path(path).name}: no 'survey' sheet found. Is this an XLSForm?")

    form = Form()
    survey = sheets["survey"]
    survey.columns = [str(c).strip() for c in survey.columns]
    if "type" not in survey.columns or "name" not in survey.columns:
        raise ValueError(f"{Path(path).name}: the survey sheet needs 'type' and 'name' columns.")
    survey = survey.dropna(subset=["type"])
    s_label = _label_column(survey)

    def cell(row, col):
        v = row.get(col)
        return str(v).strip() if col in survey.columns and pd.notna(v) and str(v).strip() else None

    repeat_stack: list[str] = []
    conditions: list[str | None] = []  # skip logic of the open groups / repeats
    for _, row in survey.iterrows():
        raw_type = str(row["type"]).strip()
        structural = raw_type.lower().replace("_", " ")
        name = snake(row["name"]) if pd.notna(row.get("name")) else ""
        label = str(row[s_label]).strip() if s_label and pd.notna(row[s_label]) else None
        if structural in {"begin repeat", "begin group"}:
            conditions.append(cell(row, "relevant"))
            if structural == "begin repeat":
                form.repeats[name] = Repeat(name, label, repeat_stack[-1] if repeat_stack else None)
                repeat_stack.append(name)
            continue
        if structural in {"end repeat", "end group"}:
            if conditions:
                conditions.pop()
            if structural == "end repeat" and repeat_stack:
                repeat_stack.pop()
            continue
        if not name:
            continue
        parts = raw_type.split()
        qtype = parts[0]
        if qtype == "note":
            continue
        list_name = parts[1] if len(parts) > 1 and qtype in {"select_one", "select_multiple"} else None
        conds = [c for c in conditions + [cell(row, "relevant")] if c]
        form.questions[name] = Question(name=name, qtype=qtype, list_name=list_name, label=label,
                                        repeat=repeat_stack[-1] if repeat_stack else None,
                                        relevant=" and ".join(conds) or None,
                                        required=(cell(row, "required") or "").lower() in {"yes", "true", "true()"})

    if "choices" in sheets:
        choices = sheets["choices"]
        choices.columns = [str(c).strip() for c in choices.columns]
        list_col = "list_name" if "list_name" in choices.columns else "list name"
        if list_col in choices.columns and "name" in choices.columns:
            choices = choices.dropna(subset=[list_col, "name"])
            c_label = _label_column(choices)
            for _, row in choices.iterrows():
                lst = str(row[list_col]).strip()
                value = code_key(row["name"])
                has_label = c_label and pd.notna(row[c_label]) and str(row[c_label]).strip()
                if not has_label:
                    form.unlabelled.setdefault(lst, []).append(value)
                label = row[c_label] if has_label else value
                form.choices.setdefault(lst, {})[value] = str(label).strip()

    if "settings" in sheets and "form_title" in sheets["settings"].columns:
        titles = sheets["settings"]["form_title"].dropna()
        form.title = str(titles.iloc[0]).strip() if not titles.empty else None

    return form
