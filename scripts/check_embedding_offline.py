#!/usr/bin/env python3
"""
check_embedding_offline.py — Phase 0 de-risk: prove all-MiniLM-L6-v2 loads & encodes OFFLINE.

Forces Hugging Face into offline mode, loads the SentenceTransformer from the local snapshot
folder, encodes a few strings, and asserts a 384-dim normalised vector. Also sanity-checks that a
*related* pair scores higher (cosine) than an *unrelated* pair — the property vector_search needs.

Run:  python scripts/check_embedding_offline.py
"""
from __future__ import annotations

import glob
import os
import sys

# Force offline BEFORE importing any HF library — no network, ever.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_model_path() -> str:
    """EMBED_MODEL_PATH if set, else the complete local HF-cache snapshot (one with config.json)."""
    env = os.environ.get("EMBED_MODEL_PATH")
    if env and os.path.isdir(env):
        return env
    base = os.path.join(REPO, "models--sentence-transformers--all-MiniLM-L6-v2", "snapshots")
    for snap in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.exists(os.path.join(snap, "config.json")) and \
           os.path.exists(os.path.join(snap, "model.safetensors")):
            return snap
    raise SystemExit(f"No complete local snapshot found under {base}")


def main() -> None:
    path = _resolve_model_path()
    print(f"EMBED_MODEL_PATH -> {path}")
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # not installed yet
        raise SystemExit(f"sentence-transformers not importable: {type(exc).__name__}: {exc}")

    model = SentenceTransformer(path)               # must load purely from local files
    vecs = model.encode(
        ["order checkout flow with email and currency",
         "customer order total and payment method",
         "weather sensor temperature and humidity readings"],
        normalize_embeddings=True,
    )
    dim = len(vecs[0])
    print(f"encoded OK — vectors: {len(vecs)}, dim: {dim}")
    assert dim == 384, f"expected 384-dim, got {dim}"

    # cosine (vectors are L2-normalised, so dot == cosine)
    def cos(a, b):
        return float(sum(x * y for x, y in zip(a, b)))

    related = cos(vecs[0], vecs[1])      # both about orders
    unrelated = cos(vecs[0], vecs[2])    # orders vs weather sensors
    print(f"cosine(order, order)   = {related:.3f}")
    print(f"cosine(order, sensors) = {unrelated:.3f}")
    assert related > unrelated, "related pair should out-score unrelated pair"

    print("\nPASS — MiniLM loads offline, 384-dim, related > unrelated. Phase 1 unblocked.")


if __name__ == "__main__":
    main()
