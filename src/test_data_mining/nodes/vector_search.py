"""
vector_search.py — Retrieve similar stored cases from ChromaDB (pivot §10).

Type: vector (ChromaDB), READ-ONLY. Embeds the parsed fields + story context with the shared
offline embedder and queries the seeded collection for the top-K most similar stored datasets
(cosine; threshold 0.70). Unreachable / missing collection → ``[]`` + a gap note (LLM-only path).

🔒 Vector DB, not a graph DB. Embeddings are deterministic and offline (no model download).
"""
from __future__ import annotations

import json
import os

from ..embedding import DeterministicEmbeddingFunction, embed
from ..state import AgentState, RetrievedRecord

_DEFAULT_CHROMA = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
    "data", "sample_chroma",
)
_TOP_K = 5
# Default tuned for the offline hashed embedder (embedding.py), whose cosines run smaller than a
# trained model's. With real/Hub embeddings raise toward ~0.70. Override via CHROMA_THRESHOLD.
_THRESHOLD = 0.40


def vector_search(state: AgentState) -> dict:
    """LangGraph node: return stored datasets similar to the parsed fields/story."""
    fields = state.get("parsed_fields", [])
    if not fields:
        return {"retrieved_data": [], "gaps": ["vector_search: no parsed fields to query"]}

    query = " ".join(f.name for f in fields)
    threshold = float(os.environ.get("CHROMA_THRESHOLD", _THRESHOLD))
    path = os.environ.get("CHROMA_PATH", _DEFAULT_CHROMA)
    coll = os.environ.get("CHROMA_COLLECTION", "tdm_cases")

    try:
        import chromadb

        client = chromadb.PersistentClient(path=path)
        col = client.get_collection(coll, embedding_function=DeterministicEmbeddingFunction())
        res = col.query(query_embeddings=[embed(query)], n_results=_TOP_K)
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
        retrieved.append(RetrievedRecord(
            test_case_id=meta.get("test_case_id", _id),
            similarity_score=round(similarity, 4),
            fields=flds,
        ))

    print(f"NODE_EXIT vector_search: {len(retrieved)} similar case(s) (>= {threshold})")
    return {"retrieved_data": retrieved, "gaps": []}
