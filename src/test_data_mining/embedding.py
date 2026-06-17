"""
embedding.py — Deterministic, offline text embedding (no model download).

A hashed bag-of-tokens projected to a fixed dimension and L2-normalised, so cosine similarity
is meaningful. Uses a STABLE hash (md5) — not Python's salted ``hash()`` — so embeddings match
across processes (the fixtures generator seeds ChromaDB; `vector_search` queries it later).

Shared by ``scripts/generate_fixtures.py`` and ``nodes/vector_search.py``. Spec §2.6 / pivot §9:
ChromaDB is the vector store; the embedder is intentionally simple and dependency-free.
"""
from __future__ import annotations

import hashlib
import math
import re

_DIM = 64
_TOKEN = re.compile(r"[a-z0-9_]+")


def _bucket(token: str, dim: int) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim


def embed(text: str, dim: int = _DIM) -> list[float]:
    """Embed text into a unit-length vector of length ``dim`` (deterministic across runs)."""
    vec = [0.0] * dim
    for tok in _TOKEN.findall((text or "").lower()):
        vec[_bucket(tok, dim)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class DeterministicEmbeddingFunction:
    """ChromaDB-compatible embedding function wrapping :func:`embed`.

    Passed to ``create_collection``/``get_collection`` so Chroma never reaches for a default
    (downloadable) model. We also pass embeddings explicitly on add/query, so this is belt-and-braces.
    """

    def __call__(self, input):  # noqa: A002 - chroma's parameter name is `input`
        return [embed(t) for t in input]

    def name(self) -> str:
        return "tdm-deterministic"

    def is_legacy(self) -> bool:
        return False
