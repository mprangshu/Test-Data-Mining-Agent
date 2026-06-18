#!/usr/bin/env python3
"""Phase 1 threshold tuning — show real MiniLM cosine scores for the seeded ChromaDB collection.

Runs the actual `vector_search` query context against each seeded dataset and prints the cosine
similarity, so we can pick CHROMA_THRESHOLD from data instead of guessing. Read-only.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from test_data_mining.embedding import active_embedder_name, context_text, embed_text  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    import chromadb

    path = os.path.join(REPO, "data", "sample_chroma")
    client = chromadb.PersistentClient(path=path)
    col = client.get_collection("tdm_cases")

    print(f"embedder: {active_embedder_name()}  |  collection count: {col.count()}\n")

    # The real query the demo issues: order-flow fields + their categories.
    order_fields = ["order_id", "customer_name", "email", "country", "currency",
                    "payment_method", "item_count", "order_total", "order_status", "created_at"]
    order_cats = ["Identifier", "PII", "Identity", "Reference", "Financial", "Quantity", "Temporal"]
    # An UNRELATED query (sensors) — should score low against the order datasets.
    sensor_fields = ["sensor_id", "temperature_c", "humidity_pct", "reading_at", "location"]

    for label, flds, cats in [("ORDER query", order_fields, order_cats),
                              ("SENSOR query", sensor_fields, ["Identifier", "Numeric", "Temporal"])]:
        q = context_text(flds, tags=sorted(set(cats)))
        res = col.query(query_embeddings=[embed_text(q)], n_results=10)
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        print(f"{label}:")
        for i, _id in enumerate(ids):
            sim = 1.0 - float(dists[i])
            print(f"  {_id:24s} cosine={sim:.3f}")
        print()


if __name__ == "__main__":
    main()
