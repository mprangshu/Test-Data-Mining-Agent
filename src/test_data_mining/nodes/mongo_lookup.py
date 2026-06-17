"""
mongo_lookup.py — Read existing test data from MongoDB (pivot §10).

Type: deterministic, READ-ONLY (invariant #1: the mine phase never writes). Matches stored
datasets to the parsed fields by field-name overlap (or test-case id), returning them as
``existing_data`` for reuse. Uses MongoDB when ``MONGODB_URI`` is set, otherwise a local JSON
seed (``data/sample_mongo/`` or ``MONGO_LOCAL_DIR``). Unreachable / empty → ``[]`` + a gap note
(the LLM-only generation path — expected on a first run).
"""
from __future__ import annotations

import glob
import json
import os

from ..state import AgentState, ExistingRecord

_DEFAULT_LOCAL = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
    "data", "sample_mongo",
)


def _load_docs() -> tuple[list[dict], list[str]]:
    uri = os.environ.get("MONGODB_URI")
    if uri:
        try:
            from pymongo import MongoClient

            client = MongoClient(uri, serverSelectionTimeoutMS=1500)
            db = client[os.environ.get("MONGODB_DB", "qea_hub")]
            docs = list(db["test_data_mining_datasets"].find({}, {"_id": False}))
            return docs, ([] if docs else ["mongo_lookup: MongoDB has no stored datasets yet"])
        except Exception as exc:  # unreachable → degrade (invariant #4)
            return [], [f"mongo_lookup: MongoDB unavailable ({type(exc).__name__}); LLM-only path"]

    local = os.environ.get("MONGO_LOCAL_DIR", _DEFAULT_LOCAL)
    if not os.path.isdir(local):
        return [], ["mongo_lookup: no MongoDB configured and no local seed; LLM-only path"]
    docs = []
    for fp in sorted(glob.glob(os.path.join(local, "*.json"))):
        try:
            with open(fp, encoding="utf-8") as f:
                docs.append(json.load(f))
        except (OSError, json.JSONDecodeError) as exc:
            return docs, [f"mongo_lookup: skipped {os.path.basename(fp)} ({type(exc).__name__})"]
    return docs, ([] if docs else ["mongo_lookup: local seed dir is empty; LLM-only path"])


def mongo_lookup(state: AgentState) -> dict:
    """LangGraph node: return stored datasets matching the parsed fields."""
    fields = state.get("parsed_fields", [])
    field_names = {f.name for f in fields}
    source_ids = {i for f in fields for i in f.source_test_ids}

    docs, gaps = _load_docs()
    existing: list[ExistingRecord] = []
    for d in docs:
        dfields = d.get("fields", {}) or {}
        if (field_names & set(dfields)) or (d.get("test_case_id") in source_ids):
            existing.append(ExistingRecord(
                test_case_id=d.get("test_case_id", ""),
                label=d.get("label", ""),
                tags=d.get("tags", []),
                fields=dfields,
            ))

    print(f"NODE_EXIT mongo_lookup: {len(existing)} existing dataset(s) matched")
    return {"existing_data": existing, "gaps": gaps}
