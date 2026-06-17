"""
parse.py — Extract required fields + scenario types from the PRIMARY inputs.

Type: deterministic. Reads ``<input_path>/test_cases/`` (or ``input_path`` itself) and supports
``.xlsx``, ``.csv``, ``.json``, ``.txt`` (Gherkin / acceptance criteria). Produces
``parsed_fields`` (the list of fields to generate data for). Never crashes → notes to ``gaps``.

Convention (pivot §10): for tabular inputs, **column headers are field names**; columns that
*label* a scenario (``scenario_type`` / ``data_category`` / ``scenario_tag``) and id columns
(``test_case_id`` …) are not fields. For Gherkin ``.txt``, ``<placeholders>`` are the fields.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import OrderedDict

from ..state import AgentState, ParsedField

# Columns that label/identify rather than name a data field.
SCENARIO_COLS = {"scenario_type", "data_category"}
TAG_COLS = {"scenario_tag"}
ID_COLS = {"test_case_id", "test_id", "testcase_id"}
_NON_FIELD = SCENARIO_COLS | TAG_COLS | ID_COLS

_CANON_SCEN = {"valid", "boundary", "negative", "edge"}

# (name substrings, category, constraints)
_CATEGORY_RULES = [
    (("email",), "Identity", ["required", "email_format"]),
    (("card_number", "card", "cvv", "iban"), "PII", ["required", "masked"]),
    (("currency",), "Reference", ["required", "ISO-4217"]),
    (("country",), "Reference", ["required", "ISO-3166"]),
    (("order_total", "total", "amount", "price", "balance"), "Financial", ["required", ">=0"]),
    (("item_count", "count", "quantity", "qty"), "Quantity", ["required", "integer"]),
    (("payment", "method"), "Reference", ["required"]),
    (("customer", "name", "first_name", "last_name"), "PII", ["required"]),
    (("created_at", "date", "timestamp", "time"), "Temporal", ["required", "ISO-8601"]),
    (("status",), "Reference", ["required"]),
    (("coupon", "code", "promo"), "Reference", []),
    (("order_id", "id"), "Identifier", ["required", "unique"]),
]


def _infer(name: str) -> tuple[str, list[str]]:
    low = name.lower()
    for subs, cat, cons in _CATEGORY_RULES:
        if any(s in low for s in subs):
            return cat, list(cons)
    return "General", ["required"]


def _norm_scenarios(values) -> list[str]:
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        key = str(v).strip().lower()
        if key in _CANON_SCEN and key not in out:
            out.append(key)
    return out


def _emit(acc: "OrderedDict[str, dict]", name: str, scenarios: list[str], ids: list[str]) -> None:
    name = (name or "").strip()
    if not name or name in _NON_FIELD:
        return
    if name not in acc:
        cat, cons = _infer(name)
        acc[name] = {"category": cat, "constraints": cons, "scenarios": [], "ids": []}
    for s in scenarios:
        if s not in acc[name]["scenarios"]:
            acc[name]["scenarios"].append(s)
    for i in ids:
        if i and i not in acc[name]["ids"]:
            acc[name]["ids"].append(i)


def _from_table(acc, headers: list[str], rows: list[dict]) -> None:
    fields = [h for h in headers if h and h not in _NON_FIELD]
    scen_vals, id_vals = [], []
    for r in rows:
        for c in SCENARIO_COLS:
            if c in r:
                scen_vals.append(r[c])
        for c in ID_COLS:
            if r.get(c):
                id_vals.append(str(r[c]))
    scenarios = _norm_scenarios(scen_vals) or ["valid"]
    for h in fields:
        _emit(acc, h, scenarios, id_vals)


def _read_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _read_xlsx(path: str):
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(c).strip() if c is not None else "" for c in next(it, [])]
        rows = [
            {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
            for r in it
        ]
    finally:
        wb.close()
    return headers, rows


def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, list) and doc and isinstance(doc[0], dict):
        headers: list[str] = []
        for row in doc:
            for k in row:
                if k not in headers:
                    headers.append(k)
        return headers, doc
    if isinstance(doc, dict):
        if isinstance(doc.get("fields"), list):
            return [str(x) for x in doc["fields"]], []
        return list(doc.keys()), [doc]
    return [], []


def _from_txt(acc, text: str, gaps: list[str], src: str) -> None:
    placeholders = re.findall(r"<([^>]+)>", text)
    low = text.lower()
    scenarios = ["valid"]
    if any(w in low for w in ("invalid", "missing", "negative", "error", "reject", "not allowed")):
        scenarios.append("negative")
    if any(w in low for w in ("boundary", "maximum", "minimum", "zero", "limit", "empty")):
        scenarios.append("boundary")
    if "edge" in low:
        scenarios.append("edge")
    for p in placeholders:
        _emit(acc, p.strip(), scenarios, [])
    if not placeholders:
        gaps.append(f"parse: no <placeholders> found in {src}")


def parse(state: AgentState) -> dict:
    """LangGraph node: read the primary test-case inputs → parsed_fields."""
    base = state["input_path"]
    tc_dir = os.path.join(base, "test_cases")
    root = tc_dir if os.path.isdir(tc_dir) else base

    if not os.path.isdir(root):
        return {"parsed_fields": [], "gaps": [f"parse: input dir not found: {root}"]}

    acc: "OrderedDict[str, dict]" = OrderedDict()
    gaps: list[str] = []
    files = [f for f in sorted(os.listdir(root)) if os.path.isfile(os.path.join(root, f))]
    for fn in files:
        ext = os.path.splitext(fn)[1].lower()
        fp = os.path.join(root, fn)
        try:
            if ext == ".csv":
                _from_table(acc, *_read_csv(fp))
            elif ext == ".xlsx":
                _from_table(acc, *_read_xlsx(fp))
            elif ext == ".json":
                _from_table(acc, *_read_json(fp))
            elif ext == ".txt":
                with open(fp, encoding="utf-8") as f:
                    _from_txt(acc, f.read(), gaps, fn)
        except Exception as exc:  # never crash — flag and continue (spec §1.4)
            gaps.append(f"parse: skipped {fn} ({type(exc).__name__}: {exc})")

    fields = [
        ParsedField(name=n, category=d["category"], constraints=d["constraints"],
                    source_test_ids=d["ids"], scenario_types=d["scenarios"] or ["valid"])
        for n, d in acc.items()
    ]
    if not fields:
        gaps.append("parse: no fields extracted from primary inputs")

    print(f"NODE_EXIT parse: {len(fields)} fields from {len(files)} file(s)")
    return {"parsed_fields": fields, "gaps": gaps}
