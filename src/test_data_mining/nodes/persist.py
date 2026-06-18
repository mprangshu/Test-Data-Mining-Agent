"""
persist.py — Save the generated dataset back to the stores for reuse (pivot §10, G5).

Type: deterministic, GATED. Only writes on an explicit save decision. Writes the dataset to
**MongoDB** (when ``MONGODB_URI`` is set) else a local JSON seed in ``data/sample_mongo/`` — the
same place ``mongo_lookup`` reads, so saving closes the reuse loop — and **upserts** the case into
**ChromaDB** so ``vector_search`` can retrieve it next time. 🔒 No Neo4j, no ``KG_SIGNAL_*``.

The write helper ``write_dataset`` is also called directly by the backend ``/persist`` endpoint
(the save gate happens after the analyst sees the dataset, so the graph node itself only writes
if ``persist_decision`` was pre-set).
"""
from __future__ import annotations

import glob  # noqa: F401  (kept for parity with mongo_lookup's local-dir scanning)
import json
import os
from datetime import datetime, timezone

from ..embedding import DeterministicEmbeddingFunction, embed
from ..state import AgentState

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_META_COLS = {"scenario_tag", "data_category"}


def _mongo_dir() -> str:
    return os.environ.get("MONGO_LOCAL_DIR", os.path.join(_REPO, "data", "sample_mongo"))


def _chroma_path() -> str:
    return os.environ.get("CHROMA_PATH", os.path.join(_REPO, "data", "sample_chroma"))


def _safe(label: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in (label or "dataset"))


def _fields_from_rows(rows: list[dict]) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in rows:
        for k, v in r.items():
            if k in _META_COLS:
                continue
            out.setdefault(k, [])
            if v not in out[k]:
                out[k].append(v)
    return out


def _upsert_chroma(label: str, fields: dict, gaps: list[str]) -> bool:
    try:
        import chromadb

        client = chromadb.PersistentClient(path=_chroma_path())
        ef = DeterministicEmbeddingFunction()
        try:
            col = client.get_collection("tdm_cases", embedding_function=ef)
        except Exception:
            col = client.create_collection("tdm_cases", metadata={"hnsw:space": "cosine"},
                                           embedding_function=ef)
        ctx = " ".join(fields.keys())
        col.upsert(ids=[label], embeddings=[embed(ctx)], documents=[ctx],
                   metadatas=[{"test_case_id": label, "label": label, "fields": json.dumps(fields)}])
        return True
    except Exception as exc:
        gaps.append(f"persist: ChromaDB upsert skipped ({type(exc).__name__})")
        return False


def write_dataset(final_dataset: list[dict], label: str, tags: list[str], report=None) -> dict:
    """Write the dataset to MongoDB (or local seed) + upsert ChromaDB. Returns a receipt."""
    fields = _fields_from_rows(final_dataset or [])
    doc = {
        "test_case_id": label, "label": label, "tags": tags or [],
        "fields": fields, "row_count": len(final_dataset or []),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    gaps: list[str] = []
    location = None

    uri = os.environ.get("MONGODB_URI")
    if uri:
        try:
            from pymongo import MongoClient

            client = MongoClient(uri, serverSelectionTimeoutMS=1500)
            db = client[os.environ.get("MONGODB_DB", "qea_hub")]
            db["test_data_mining_datasets"].replace_one({"label": label}, doc, upsert=True)
            location = f"mongodb://{db.name}/test_data_mining_datasets/{label}"
        except Exception as exc:  # configured but unreachable → local fallback (spec §1.4)
            gaps.append(f"persist: MongoDB unavailable ({type(exc).__name__}); wrote local seed")
    if not location:
        d = _mongo_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{_safe(label)}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        location = path

    chroma_ok = _upsert_chroma(label, fields, gaps)
    return {"label": label, "rows": doc["row_count"], "fields": list(fields),
            "location": location, "chroma_indexed": chroma_ok, "gaps": gaps}


def persist(state: AgentState) -> dict:
    """LangGraph node: write only if the save gate was pre-set; otherwise a no-op pass-through."""
    if not state.get("persist_decision"):
        print("NODE_EXIT persist: save gate not set (no write)")
        return {}
    receipt = write_dataset(
        state.get("final_dataset", []),
        state.get("persist_label") or "generated_dataset",
        state.get("persist_tags") or [],
        state.get("report"),
    )
    print(f"NODE_EXIT persist: saved -> {receipt['location']}")
    return {"persist_receipt": receipt, "gaps": receipt.get("gaps", [])}
