"""
Phase 8 — embeddings load OFFLINE and are semantically meaningful (CONTEXT-v3 §4).

Asserts the active embedder encodes to the expected dimension and that a related pair out-scores an
unrelated pair (the property `vector_search` relies on). Runs with the network off; if the MiniLM
stack/model isn't present the deterministic fallback is used (still asserts related > unrelated).

Run: pytest -q tests/test_embedding_local.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Force offline before importing the embedding module (no download, ever).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.embedding import active_embedder_name, embed_text   # noqa: E402


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))   # vectors are L2-normalised → dot == cosine


def test_dimension_matches_active_embedder():
    name = active_embedder_name()
    dim = len(embed_text("order email currency country payment_method"))
    assert dim == (384 if name == "minilm-l6-v2" else 64)


def test_related_outscores_unrelated():
    base = embed_text("customer order email currency country payment total")
    related = embed_text("checkout order currency country payment amount")
    unrelated = embed_text("weather sensor temperature humidity wind reading")
    assert _cos(base, related) > _cos(base, unrelated)
