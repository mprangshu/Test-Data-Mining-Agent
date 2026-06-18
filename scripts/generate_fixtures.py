#!/usr/bin/env python3
"""
generate_fixtures.py — Seed everything the v2 demo needs (pivot §9).

Builds, from the canonical ``tdm_demo_output.csv`` (order-flow schema), a coherent demo where:
  * MongoDB (local JSON seed) holds the *valid* values for a few fields (so `mongo_lookup`
    returns real existing data to REUSE),
  * the supporting result files show *valid* scenarios passing (→ realistic `seed_values`) and
    *negative* scenarios failing, with *boundary*/*edge* absent (→ `coverage_gaps`),
  * ChromaDB is seeded so `vector_search` returns similar stored cases.

Outputs (all under <repo>/data/):
  sample_upload/test_cases/order_flow_tests.csv   primary input — field list + scenario types
  sample_upload/test_cases/login_flow_tests.txt   primary input — Gherkin BDD
  sample_upload/results/junit.xml                 supporting — valid pass + negative fail
  sample_upload/results/playwright.json           supporting — valid pass
  sample_mongo/*.json                             MongoDB seed datasets
  sample_chroma/                                  ChromaDB persistent store (gitignored)
  golden/expectations_v2.json                     what tests assert the agent recovers

stdlib only, except ChromaDB for the vector seed (optional — skipped with a warning if absent).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from test_data_mining.embedding import embed, DeterministicEmbeddingFunction  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(REPO, "tdm_demo_output.csv")
DATA = os.path.join(REPO, "data")

META_COLS = {"scenario_tag", "data_category"}
# Preferred fields to pre-store in MongoDB (reused, not regenerated) — used when present in the
# source; otherwise we fall back to the first few data columns. NEVER a hardcoded schema.
_PREFERRED_REUSE = ["email", "order_total", "currency", "country"]


def _read_rows(csv_path: str) -> tuple[list[str], list[dict]]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _data_fields(headers: list[str]) -> list[str]:
    return [h for h in headers if h not in META_COLS]


def _reused_fields(data_fields: list[str]) -> list[str]:
    """Schema-agnostic: prefer the well-known reusable fields when present, else the first few."""
    preferred = [f for f in _PREFERRED_REUSE if f in data_fields]
    return preferred if len(preferred) >= 2 else data_fields[:4]


# ── primary inputs ────────────────────────────────────────────────────
def _write_test_cases(tc_dir: str, csv_path: str) -> None:
    os.makedirs(tc_dir, exist_ok=True)
    # The test-case sheet is the source CSV itself (headers = required fields; data_category
    # lists the scenario types). parse() reads it to derive parsed_fields + the original rows.
    shutil.copy(csv_path, os.path.join(tc_dir, os.path.basename(csv_path)))
    with open(os.path.join(tc_dir, "login_flow_tests.txt"), "w", encoding="utf-8") as f:
        f.write(
            "Feature: Login\n\n"
            "  Scenario: Successful login\n"
            "    Given a registered user with <email> and <password>\n"
            "    When they submit the login form\n"
            "    Then they are signed in\n\n"
            "  Scenario: Invalid password is rejected\n"
            "    Given a registered user with <email>\n"
            "    When they submit an invalid <password>\n"
            "    Then login fails with an error\n\n"
            "  Scenario: Empty email is rejected (boundary)\n"
            "    Given an empty <email>\n"
            "    Then the form shows a required-field error\n"
        )


# ── supporting result files ──────────────────────────────────────────
def _props(parent, row, data_fields):
    props = ET.SubElement(parent, "properties")
    ET.SubElement(props, "property", {"name": "scenario_type", "value": row["data_category"]})
    ET.SubElement(props, "property", {"name": "scenario_tag", "value": row["scenario_tag"]})
    for fld in data_fields:
        ET.SubElement(props, "property", {"name": fld, "value": str(row.get(fld, "") or "")})


def _write_junit(path: str, passing: list[dict], failing: list[dict], data_fields) -> None:
    suite = ET.Element("testsuite", {"name": "order_flow",
                                     "tests": str(len(passing) + len(failing)),
                                     "failures": str(len(failing))})
    for row in passing:
        case = ET.SubElement(suite, "testcase", {"classname": "order_flow", "name": row["scenario_tag"]})
        _props(case, row, data_fields)
    for row in failing:
        case = ET.SubElement(suite, "testcase", {"classname": "order_flow", "name": row["scenario_tag"]})
        _props(case, row, data_fields)
        ET.SubElement(case, "failure", {"message": f"{row['scenario_tag']} failed"}).text = "assertion failed"
    tree = ET.ElementTree(suite)
    ET.indent(tree, space="  ")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_playwright(path: str, passing: list[dict], data_fields) -> None:
    specs = []
    for row in passing:
        ann = [{"type": "scenario_type", "description": row["data_category"]},
               {"type": "scenario_tag", "description": row["scenario_tag"]}]
        ann += [{"type": fld, "description": str(row.get(fld, "") or "")} for fld in data_fields]
        specs.append({"title": row["scenario_tag"], "annotations": ann,
                      "tests": [{"results": [{"status": "passed"}]}]})
    doc = {"config": {"metadata": {}}, "suites": [{"title": "order_flow", "specs": specs}]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


# ── MongoDB seed (local JSON) ─────────────────────────────────────────
def _write_mongo(mongo_dir: str, valid_rows: list[dict], reused_fields: list[str]) -> list[dict]:
    os.makedirs(mongo_dir, exist_ok=True)
    docs = [
        {"test_case_id": "order_flow", "label": "order_flow_v1", "tags": ["order", "checkout", "valid"],
         "fields": {f: [r[f] for r in valid_rows if r.get(f)] for f in reused_fields}},
    ]
    # Optional second dataset built only from identity-ish fields that actually exist (no hardcoding).
    identity = [f for f in ("email", "customer_name", "username", "name") if any(r.get(f) for r in valid_rows)]
    if identity:
        docs.append(
            {"test_case_id": "customer_profile", "label": "customer_profiles_v1", "tags": ["identity", "valid"],
             "fields": {f: [r[f] for r in valid_rows if r.get(f)] for f in identity}})
    for d in docs:
        with open(os.path.join(mongo_dir, f"{d['label']}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    return docs


# ── ChromaDB seed ─────────────────────────────────────────────────────
def _seed_chroma(chroma_dir: str, docs: list[dict]) -> bool:
    try:
        import chromadb
    except Exception as exc:  # optional — demo still works, vector_search just returns []
        print(f"  (skipped ChromaDB seed: {type(exc).__name__}: {exc})")
        return False
    shutil.rmtree(chroma_dir, ignore_errors=True)
    os.makedirs(chroma_dir, exist_ok=True)
    client = chromadb.PersistentClient(path=chroma_dir)
    ef = DeterministicEmbeddingFunction()
    col = client.create_collection("tdm_cases", metadata={"hnsw:space": "cosine"}, embedding_function=ef)
    ids, embs, metas, texts = [], [], [], []
    for d in docs:
        # Embed the field-name context (label/tags kept in metadata, not the vector) so cosine
        # reflects field overlap with the query — meaningful under the offline hashed embedder.
        context = " ".join(d["fields"].keys())
        ids.append(d["label"])
        embs.append(embed(context))
        metas.append({"test_case_id": d["test_case_id"], "label": d["label"],
                      "fields": json.dumps(d["fields"])})
        texts.append(context)
    col.add(ids=ids, embeddings=embs, documents=texts, metadatas=metas)
    return True


# ── main ──────────────────────────────────────────────────────────────
def _assert_no_placeholders(docs: list[dict]) -> None:
    """Fail loudly if a `sample_value_*` placeholder leaked into the MongoDB seed (IMPROVEMENT.md §6)."""
    for d in docs:
        for vals in d["fields"].values():
            for v in vals:
                if str(v).strip().lower().startswith("sample_value_"):
                    raise SystemExit(f"placeholder leaked into seed {d['label']}: {v!r}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Seed v2 demo fixtures from a source CSV (any schema).")
    ap.add_argument("--source", default=DEFAULT_CSV,
                    help="source CSV (columns = fields; data_category column = scenario types). "
                         f"Default: {os.path.relpath(DEFAULT_CSV, REPO)}")
    args = ap.parse_args(argv)
    csv_path = os.path.abspath(args.source)

    if not os.path.exists(csv_path):
        raise SystemExit(f"Source CSV not found: {csv_path}")
    headers, rows = _read_rows(csv_path)
    data_fields = _data_fields(headers)
    reused_fields = _reused_fields(data_fields)

    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r.get("data_category", "valid"), []).append(r)
    valid = by_cat.get("valid", [])
    negative = by_cat.get("negative", [])

    upload = os.path.join(DATA, "sample_upload")
    shutil.rmtree(upload, ignore_errors=True)
    _write_test_cases(os.path.join(upload, "test_cases"), csv_path)

    mid = len(valid) // 2
    _write_junit(os.path.join(upload, "results", "junit.xml"),
                 passing=valid[:mid], failing=negative, data_fields=data_fields)
    _write_playwright(os.path.join(upload, "results", "playwright.json"),
                      passing=valid[mid:], data_fields=data_fields)

    docs = _write_mongo(os.path.join(DATA, "sample_mongo"), valid, reused_fields)
    _assert_no_placeholders(docs)
    chroma_ok = _seed_chroma(os.path.join(DATA, "sample_chroma"), docs)

    golden = {
        "all_fields": data_fields,
        "reused_fields": reused_fields,                 # mongo_lookup should return these
        "exercised_scenarios": ["valid", "negative"],   # present in result files
        "gap_scenario_types": ["boundary", "edge"],     # absent in results → coverage gaps
    }
    os.makedirs(os.path.join(DATA, "golden"), exist_ok=True)
    with open(os.path.join(DATA, "golden", "expectations_v2.json"), "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2)

    print(f"Generated v2 fixtures from {os.path.basename(csv_path)}:")
    print(f"  test cases   -> {upload}/test_cases ({len(data_fields)} fields, {len(rows)} rows)")
    print(f"  results      -> {upload}/results (valid pass: {len(valid)}, negative fail: {len(negative)})")
    print(f"  MongoDB seed -> {DATA}/sample_mongo ({len(docs)} datasets, reused fields {reused_fields})")
    print(f"  ChromaDB     -> {'seeded' if chroma_ok else 'SKIPPED'} at {DATA}/sample_chroma")
    print(f"  golden       -> {DATA}/golden/expectations_v2.json (gaps: boundary, edge)")


if __name__ == "__main__":
    main()
