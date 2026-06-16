"""
failure_clustering.py — Group failures by root-cause signature (G3, spec §2.3 & §2.6).

Type: vector + (optional) LLM. This REPLACES the exact-match placeholder that lived in
stubs.py with real semantic clustering.

Pipeline (spec §2.6 — a VECTOR problem, never a graph one):
  1. Collect failures (outcome in failed/error with a message or stack).
  2. Normalise each message+stack into a signature (strip line numbers, addresses,
     timestamps, UUIDs, durations) so superficially-different failures with the same root
     cause collapse together.
  3. Embed each signature locally (deterministic signed token-hashing → L2-normalised vector)
     and cluster by cosine similarity in **ChromaDB**. A pure-Python cosine fallback runs if
     ChromaDB can't initialise, so the node degrades gracefully and never crashes.
  4. Label each cluster. The DEFAULT label is deterministic + grounded in the signature.
     A Hub LLM labeler can be injected (see ``label_clusters``); it only *relabels* — the
     vector DB still *forms* the clusters — and a label is accepted only if its terms appear
     in the cluster's real messages (anti-hallucination, spec §2.3).

Offline by design: embeddings are computed in-process, so no embedding-model download and no
network are required. The LLM labeler is optional and absent in this standalone demo (the spec
routes it through the Hub's Python LLM router, never a standalone key in this repo).
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

from ..state import AgentState, FailureCluster, TestResult

_DIM = 512
_COSINE_DISTANCE_THRESHOLD = 0.30  # distance <= 0.30  <=>  cosine similarity >= 0.70


# --------------------------------------------------------------------------- #
# 1–2. Signature normalisation
# --------------------------------------------------------------------------- #
def normalise_signature(message: str | None, stack: str | None = None) -> str:
    """Collapse a raw failure message into a stable root-cause signature."""
    s = (message or "").strip()
    if not s and stack:
        s = stack.strip().splitlines()[0] if stack.strip() else ""
    s = re.sub(r"0x[0-9a-fA-F]+", "0x#", s)                                   # hex addresses
    s = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*", "<ts>", s)       # ISO timestamps
    s = re.sub(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", "<uuid>", s)  # UUIDs
    s = re.sub(r"(?::\d+)+", ":#", s)                                          # :line[:col]
    s = re.sub(r"\b\d+(?:\.\d+)?(ms|s|MB|KB|GB)?\b", "#", s)                   # numbers/durations
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --------------------------------------------------------------------------- #
# 3. Local embedding (deterministic, offline) + clustering
# --------------------------------------------------------------------------- #
def _tokens(sig: str) -> list[str]:
    words = re.findall(r"[a-zA-Z#]+", sig.lower())
    bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return words + bigrams


def embed(sig: str) -> list[float]:
    """Signed token-hashing embedding, L2-normalised — deterministic and dependency-free."""
    vec = [0.0] * _DIM
    for tok in _tokens(sig):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % _DIM
        vec[idx] += 1.0 if (h >> 8) & 1 else -1.0   # signed hashing reduces collisions
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cluster_with_chroma(items: list[tuple[int, str, list[float]]], threshold: float) -> dict[int, str]:
    """Greedy nearest-rep clustering using ChromaDB cosine space. Raises if Chroma is unusable."""
    import chromadb
    from chromadb.config import Settings

    client = chromadb.EphemeralClient(Settings(anonymized_telemetry=False))
    # Custom embedding function prevents ChromaDB from loading its default (network) model.
    col = client.create_collection(
        "failure_signatures",
        metadata={"hnsw:space": "cosine"},
        embedding_function=_NoOpEF(),
    )
    assignments: dict[int, str] = {}
    next_id = 0
    for idx, sig, emb in items:
        if col.count() > 0:
            res = col.query(query_embeddings=[emb], n_results=1)
            dist = res["distances"][0][0]
            if dist <= threshold:
                assignments[idx] = res["ids"][0][0]
                continue
        cid = f"c{next_id:03d}"
        next_id += 1
        col.add(ids=[cid], embeddings=[emb], documents=[sig])
        assignments[idx] = cid
    return assignments


class _NoOpEF:
    """ChromaDB embedding function we never actually call (we always pass embeddings)."""

    def __call__(self, input):  # noqa: A002  (Chroma's parameter name is `input`)
        return [embed(t) for t in input]

    @staticmethod
    def name() -> str:
        return "local-hash"


def _cluster_pure_python(items: list[tuple[int, str, list[float]]], threshold: float) -> dict[int, str]:
    """Fallback: identical greedy clustering with in-process cosine (vectors are L2-normalised)."""
    reps: list[tuple[str, list[float]]] = []
    assignments: dict[int, str] = {}
    next_id = 0
    for idx, _sig, emb in items:
        best_cid, best_sim = None, -1.0
        for cid, remb in reps:
            sim = sum(a * b for a, b in zip(emb, remb))
            if sim > best_sim:
                best_sim, best_cid = sim, cid
        if best_cid is not None and (1.0 - best_sim) <= threshold:
            assignments[idx] = best_cid
        else:
            cid = f"c{next_id:03d}"
            next_id += 1
            reps.append((cid, emb))
            assignments[idx] = cid
    return assignments


# --------------------------------------------------------------------------- #
# 4. Labelling — deterministic default + optional grounded LLM labeler
# --------------------------------------------------------------------------- #
def deterministic_label(signature: str) -> str:
    """A readable, grounded label derived straight from the signature (no LLM)."""
    m = re.match(r"([A-Za-z.]*(?:Error|Exception|Failure))\b:?\s*(.*)", signature)
    if m:
        etype = m.group(1).split(".")[-1]
        rest = " ".join(m.group(2).split()[:6]).strip()
        return f"{etype}: {rest}".rstrip(": ").strip() if rest else etype
    return signature[:60] if signature else "uncategorised failure"


def _grounded(label: str, messages: list[str]) -> bool:
    """Anti-hallucination: accept an LLM label only if its salient terms appear in the data."""
    corpus = " ".join(messages).lower()
    terms = [t for t in re.findall(r"[a-zA-Z]{4,}", label.lower())]
    if not terms:
        return False
    hits = sum(1 for t in terms if t in corpus)
    return hits / len(terms) >= 0.5


def label_clusters(clusters: list[FailureCluster], messages_by_cluster: dict[str, list[str]], llm=None) -> None:
    """Label clusters in place. With no ``llm`` the deterministic label is kept; with an
    injected Hub labeler, its proposal is used only if grounded in the cluster's messages."""
    for c in clusters:
        if llm is None:
            continue
        try:
            proposed = llm(c.signature, messages_by_cluster.get(c.cluster_id, []))
        except Exception:
            continue  # never let a labeler failure break the deterministic result
        if proposed and _grounded(proposed, messages_by_cluster.get(c.cluster_id, [])):
            c.label = proposed.strip()


# --------------------------------------------------------------------------- #
# Node
# --------------------------------------------------------------------------- #
def failure_clustering(state: AgentState) -> dict:
    """LangGraph node: cluster failures by signature via ChromaDB cosine similarity."""
    results: list[TestResult] = state.get("raw_results", [])
    failures = [r for r in results if r.outcome in ("failed", "error") and (r.message or r.stack_trace)]
    if not failures:
        print("NODE_EXIT failure_clustering: 0 clusters (no failures)")
        return {"failure_clusters": []}

    items: list[tuple[int, str, list[float]]] = []
    sig_by_idx: dict[int, str] = {}
    for i, r in enumerate(failures):
        sig = normalise_signature(r.message, r.stack_trace)
        sig_by_idx[i] = sig
        items.append((i, sig, embed(sig)))

    gaps: list[str] = []
    try:
        assignments = _cluster_with_chroma(items, _COSINE_DISTANCE_THRESHOLD)
    except Exception as exc:  # ChromaDB missing/unusable — degrade, don't crash (spec §1.4)
        assignments = _cluster_pure_python(items, _COSINE_DISTANCE_THRESHOLD)
        gaps.append(f"failure_clustering: ChromaDB unavailable ({type(exc).__name__}); used in-process cosine")

    grouped: dict[str, list[int]] = defaultdict(list)
    for i, _sig, _emb in items:
        grouped[assignments[i]].append(i)

    clusters: list[FailureCluster] = []
    messages_by_cluster: dict[str, list[str]] = {}
    # Largest clusters first; re-id sequentially so output ids are stable & readable.
    for new_n, (_cid, idxs) in enumerate(sorted(grouped.items(), key=lambda kv: -len(kv[1]))):
        sigs = [sig_by_idx[i] for i in idxs]
        rep_sig = Counter(sigs).most_common(1)[0][0]
        rep_trace = next((failures[i].stack_trace for i in idxs if failures[i].stack_trace), "")
        cid = f"c{new_n:03d}"
        messages_by_cluster[cid] = [failures[i].message or "" for i in idxs]
        clusters.append(FailureCluster(
            cluster_id=cid,
            signature=rep_sig,
            count=len(idxs),
            representative_trace=rep_trace or "",
            label=deterministic_label(rep_sig),
        ))

    # LLM labelling seam (no-op here — Hub router would be injected in the platform runtime).
    label_clusters(clusters, messages_by_cluster, llm=None)

    print(f"NODE_EXIT failure_clustering: {len(clusters)} clusters from {len(failures)} failures")
    return {"failure_clusters": clusters, "gaps": gaps}
