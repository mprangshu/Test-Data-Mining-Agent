"""
embedding.py — Text embedding for ChromaDB (real model, with an offline deterministic fallback).

Primary: **all-MiniLM-L6-v2** (384-dim) via ``sentence-transformers``, loaded **offline** from a
local model snapshot (``EMBED_MODEL_PATH`` or the in-repo HF cache). Real semantic similarity makes
the "gathered" (vector) retrieval meaningful.

Fallback: a deterministic hashed bag-of-tokens (64-dim, md5, L2-normalised). Used automatically
when the model/stack can't load — so the agent still runs fully offline with no heavy deps
(invariant #4, graceful degradation). The choice is process-wide and consistent: both seeding and
querying go through :func:`get_embedding_function` / :func:`embed_text`, so a collection is always
queried with the same embedder that seeded it.

Richer context (CONTEXT-v3 Phase 1, option 2): instead of embedding bare field names, we embed a
descriptive string — title + tags + field names + a few sample values — via :func:`context_text`,
so the model places each dataset more precisely in semantic space. Schema-agnostic: it never
references a specific column name.
"""
from __future__ import annotations

import functools
import glob
import hashlib
import math
import os
import re

_DIM = 64
_TOKEN = re.compile(r"[a-z0-9_]+")
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Deterministic fallback embedder (no model, no download) ───────────
def _bucket(token: str, dim: int) -> int:
    # Assign the token to a fixed embedding bucket in the deterministic vector.
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim


def embed(text: str, dim: int = _DIM) -> list[float]:
    """Deterministic unit-length embedding of ``text`` (md5-hashed tokens).

    Inputs: `text` string, `dim` int (vector dimension).
    Output: unit-length float vector of length `dim`.
    Caller: used as the offline fallback for seeding and querying (via `embed_text` / `get_embedding_function`).
    """
    # Build a bag-of-tokens vector and normalise to unit length.
    vec = [0.0] * dim
    for tok in _TOKEN.findall((text or "").lower()):
        vec[_bucket(tok, dim)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class DeterministicEmbeddingFunction:
    """ChromaDB-compatible embedding function wrapping :func:`embed` (the fallback)."""

    def __call__(self, input):  # noqa: A002 - chroma's parameter name is `input`
        # Encode a batch (list[str]) using the deterministic fallback embedding.
        # Returns: list[list[float]] suitable for ChromaDB upsert/query.
        return [embed(t) for t in input]

    def name(self) -> str:
        # Return a stable name for the deterministic embedding function.
        return "tdm-deterministic"

    def is_legacy(self) -> bool:
        # Indicate this embedding function is compatible with modern Chroma clients.
        return False


# ── Real local MiniLM embedder (offline) ──────────────────────────────
def _resolve_model_path() -> str | None:
    """``EMBED_MODEL_PATH`` if set, else the complete in-repo HF-cache snapshot (config + weights)."""
    # Find the local MiniLM snapshot path if it exists.
    env = os.environ.get("EMBED_MODEL_PATH")
    if env and os.path.isdir(env):
        return env
    base = os.path.join(_REPO, "models--sentence-transformers--all-MiniLM-L6-v2", "snapshots")
    for snap in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.exists(os.path.join(snap, "config.json")) and \
           os.path.exists(os.path.join(snap, "model.safetensors")):
            return snap
    return None


@functools.lru_cache(maxsize=1)
def _load_st_model():
    """Load the SentenceTransformer once, OFFLINE.

    Returns the loaded model instance or `None` if no offline snapshot / import failure.
    Callers: internal wrapper functions `embed_texts` and `get_embedding_function`.
    """
    # Attempt to load the offline MiniLM model snapshot; fallback to the deterministic embedder if it fails.
    path = _resolve_model_path()
    if not path:
        print("EMBED_FALLBACK: no local MiniLM snapshot found; using deterministic embedder")
        return None
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(path)
        print(f"EMBED_MODEL: loaded all-MiniLM-L6-v2 (384-dim) offline from {os.path.basename(path)}")
        return model
    except Exception as exc:  # stack missing / load error → degrade (invariant #4)
        print(f"EMBED_FALLBACK: MiniLM unavailable ({type(exc).__name__}: {exc}); deterministic embedder")
        return None


class LocalMiniLMEmbeddingFunction:
    """ChromaDB-compatible embedding function backed by the local MiniLM model."""

    def __call__(self, input):  # noqa: A002 - chroma's parameter name is `input`
        # Encode a batch (list[str]) using the local MiniLM model and return
        # a list[list[float]] (embeddings). Normalization is applied by the model.
        model = _load_st_model()
        return model.encode(list(input), normalize_embeddings=True).tolist()

    def name(self) -> str:
        # Identify the local MiniLM embedder implementation.
        return "tdm-minilm-l6-v2"

    def is_legacy(self) -> bool:
        # Signal current Chroma API compatibility.
        return False


# ── Public API — always go through these so seed & query agree ────────
def active_embedder_name() -> str:
    # Report the current embedder name for threshold selection and logging.
    # Caller: diagnostic logging, storage metadata.
    return "minilm-l6-v2" if _load_st_model() is not None else "deterministic"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch with the active embedder (MiniLM if available, else deterministic)."""
    # Use the loaded MiniLM model when available; otherwise use deterministic hashing.
    # Output: list of vectors (list[list[float]]). Callers: `get_embedding_function`, `_upsert_chroma`.
    model = _load_st_model()
    if model is not None:
        return model.encode(list(texts), normalize_embeddings=True).tolist()
    return [embed(t) for t in texts]


def embed_text(text: str) -> list[float]:
    """Embed one string with the active embedder."""
    # Convenience wrapper for single-text embedding.
    return embed_texts([text])[0]


def get_embedding_function():
    """The ChromaDB embedding function for the active embedder (real MiniLM or deterministic)."""
    # Return a ChromaDB-compatible function based on the loaded embedder.
    # The returned callable implements the Chroma client API: it accepts a list[str]
    # and returns list[list[float]]. Used by `_upsert_chroma` and clients that need
    # to pass an embedding_function to persistent collections.
    if _load_st_model() is not None:
        return LocalMiniLMEmbeddingFunction()
    return DeterministicEmbeddingFunction()


def context_text(fields, *, tags=None, title=None, max_values: int = 4) -> str:
    """Build a descriptive embedding string from a dataset (schema-agnostic — no column names).

    ``fields`` may be a dict ``{column: [values]}`` or a list of column names. We combine an
    optional title + tags + the field names + a few sample values so the model has a rich,
    discriminative document rather than bare identifiers (CONTEXT-v3 §4, option 2).
    """
    parts: list[str] = []
    if title:
        parts.append(str(title))
    if tags:
        parts.append("tags: " + " ".join(str(t) for t in tags))
    if isinstance(fields, dict):
        parts.append("fields: " + " ".join(fields.keys()))
        sample: list[str] = []
        for vals in fields.values():
            for v in list(vals)[:max_values]:
                if str(v).strip():
                    sample.append(str(v))
        if sample:
            parts.append("values: " + " ".join(sample[: max_values * 6]))
    else:
        parts.append("fields: " + " ".join(str(f) for f in fields))
    return " | ".join(parts)
