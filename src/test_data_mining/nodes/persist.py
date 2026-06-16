"""
persist.py — Persist the report to the run store (spec §2.3).

Type: deterministic. Writes to **MongoDB** when configured (env ``MONGODB_URI``), otherwise
dumps JSON to ``data/reports/`` for local dev. 🔒 No Neo4j, no ``KG_SIGNAL_*`` events — this
agent has no knowledge-graph dependency. Degrades gracefully: if Mongo is configured but
unreachable, it falls back to a local file and notes the gap rather than crashing.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

from ..state import AgentState

_REPORTS_DIR = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
    "data", "reports",
)


def _encode(obj):
    """Recursively turn dataclasses (e.g. SuiteHealth) into JSON-safe structures."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _encode(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    return obj


def _persist_mongo(doc: dict) -> str | None:
    """Insert into MongoDB if MONGODB_URI is set; return a locator, else None."""
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    from pymongo import MongoClient  # imported lazily so the demo runs without a live Mongo

    client = MongoClient(uri, serverSelectionTimeoutMS=1500)
    db = client[os.environ.get("MONGODB_DB", "qea_hub")]
    res = db["test_data_mining_reports"].insert_one(doc)
    return f"mongodb://{db.name}/test_data_mining_reports/{res.inserted_id}"


def _persist_file(doc: dict) -> str:
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(_REPORTS_DIR, f"report_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return path


def persist(state: AgentState) -> dict:
    """LangGraph node: write the report to the run store; record where it landed."""
    report = state.get("report") or {}
    doc = _encode({
        **report,
        "gaps": state.get("gaps", []),
        "errors": state.get("errors", []),
    })

    gaps: list[str] = []
    location: str | None = None
    try:
        location = _persist_mongo(doc)
    except Exception as exc:  # configured but unreachable — fall back, don't crash (spec §1.4)
        gaps.append(f"persist: MongoDB unavailable ({type(exc).__name__}); wrote local file")
    if not location:
        location = _persist_file(doc)

    print(f"NODE_EXIT persist: report -> {location}")
    return {"report": {**report, "persisted_to": location}, "gaps": gaps}
