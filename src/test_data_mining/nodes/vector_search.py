"""
vector_search.py — Retrieve similar stored cases from ChromaDB (pivot §10).

Type: vector (ChromaDB), READ-ONLY. Embeds the parsed fields (+ categories) as a descriptive
query with the active embedder (real all-MiniLM-L6-v2 when available, deterministic fallback
otherwise) and queries the seeded collection for the top-K most similar stored datasets (cosine).
Unreachable / missing collection → ``[]`` + a gap note (LLM-only path).

🔒 Vector DB, not a graph DB. Embeddings load offline (no download); see ``embedding.py``.
"""
from __future__ import annotations

import json
import os

from ..embedding import active_embedder_name, context_text, embed_text, get_embedding_function
from ..state import AgentState, RetrievedRecord

_DEFAULT_CHROMA = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
    "data", "sample_chroma",
)
_TOP_K = 5
# Per-embedder defaults (override via CHROMA_THRESHOLD). Tuned empirically on the seeded fixtures
# (scripts/measure_similarity.py), NOT the spec's blind 0.70: with MiniLM, relevant order datasets
# score 0.40–0.60 and an unrelated (sensor) query tops out at ~0.37 — so 0.40 cleanly separates
# them. Deterministic embedder keeps its old 0.40.
_THRESHOLD_BY_EMBEDDER = {"minilm-l6-v2": 0.40, "deterministic": 0.40}


def vector_search(state: AgentState) -> dict:
    """LangGraph node: return stored datasets similar to the parsed fields/story."""
    fields = state.get("parsed_fields", [])
    if not fields:
        return {"retrieved_data": [], "gaps": ["vector_search: no parsed fields to query"]}

    # Richer query context (option 2): field names + categories, same shape as the seeded docs.
    query = context_text([f.name for f in fields],
                         tags=sorted({f.category for f in fields if f.category}))
    default_threshold = _THRESHOLD_BY_EMBEDDER.get(active_embedder_name(), 0.40)
    threshold = float(os.environ.get("CHROMA_THRESHOLD", default_threshold))
    path = os.environ.get("CHROMA_PATH", _DEFAULT_CHROMA)
    coll = os.environ.get("CHROMA_COLLECTION", "tdm_cases")

    try:
        import chromadb

        client = chromadb.PersistentClient(path=path)
        col = client.get_collection(coll, embedding_function=get_embedding_function())
        res = col.query(query_embeddings=[embed_text(query)], n_results=_TOP_K)
    except Exception as exc:  # missing store/collection → degrade (invariant #4)
        return {"retrieved_data": [],
                "gaps": [f"vector_search: ChromaDB unavailable ({type(exc).__name__}); LLM-only path"]}

    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]

    retrieved: list[RetrievedRecord] = []
    for i, _id in enumerate(ids):
        similarity = 1.0 - float(dists[i]) if i < len(dists) else 0.0
        if similarity < threshold:
            continue
        meta = metas[i] or {}
        try:
            flds = json.loads(meta.get("fields", "{}"))
        except json.JSONDecodeError:
            flds = {}
        try:
            rows = json.loads(meta.get("rows", "[]"))
        except json.JSONDecodeError:
            rows = []
        retrieved.append(RetrievedRecord(
            test_case_id=meta.get("test_case_id", _id),
            similarity_score=round(similarity, 4),
            fields=flds,
            rows=rows or [],
        ))

    print(f"NODE_EXIT vector_search: {len(retrieved)} similar case(s) "
          f"(>= {threshold}, {active_embedder_name()})")
    return {"retrieved_data": retrieved, "gaps": []}
