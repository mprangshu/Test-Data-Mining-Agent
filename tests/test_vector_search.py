"""Unit tests for the `vector_search` node (ChromaDB). Run: pytest -q tests/test_vector_search.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.embedding import context_text, embed_text, get_embedding_function  # noqa: E402
from test_data_mining.nodes.vector_search import vector_search                 # noqa: E402
from test_data_mining.state import ParsedField, initial_state                  # noqa: E402


def _state(fields):
    st = initial_state("x")
    st["parsed_fields"] = [
        ParsedField(name=n, category=c, constraints=[], source_test_ids=[], scenario_types=["valid"])
        for n, c in fields
    ]
    return st


def _node_query_context(fields):
    # Mirror exactly what vector_search builds, so the seeded doc matches → similarity ~1.0.
    return context_text([n for n, _c in fields], tags=sorted({c for _n, c in fields}))


def test_returns_similar_case(tmp_path, monkeypatch):
    import chromadb

    fields = [("email", "Identity"), ("order_total", "Financial")]
    ctx = _node_query_context(fields)
    client = chromadb.PersistentClient(path=str(tmp_path))
    # Use the ACTIVE embedder (real MiniLM or deterministic) for both seed and query, so dims agree.
    col = client.create_collection("tdm_cases", metadata={"hnsw:space": "cosine"},
                                   embedding_function=get_embedding_function())
    col.add(ids=["order_flow_v1"], embeddings=[embed_text(ctx)], documents=[ctx],
            metadatas=[{"test_case_id": "order_flow", "label": "order_flow_v1",
                        "fields": json.dumps({"email": ["a@b.com"]})}])

    monkeypatch.setenv("CHROMA_PATH", str(tmp_path))
    monkeypatch.setenv("CHROMA_COLLECTION", "tdm_cases")
    out = vector_search(_state(fields))
    assert len(out["retrieved_data"]) == 1
    rec = out["retrieved_data"][0]
    assert rec.test_case_id == "order_flow"
    assert rec.similarity_score >= 0.70          # exact-context match → ~1.0 for either embedder
    assert rec.fields["email"] == ["a@b.com"]


def test_missing_collection_degrades(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("CHROMA_COLLECTION", "tdm_cases")
    out = vector_search(_state([("email", "Identity")]))
    assert out["retrieved_data"] == []
    assert any("ChromaDB unavailable" in g for g in out["gaps"])


def test_no_fields_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path))
    out = vector_search(initial_state("x"))
    assert out["retrieved_data"] == []
    assert any("no parsed fields" in g for g in out["gaps"])
