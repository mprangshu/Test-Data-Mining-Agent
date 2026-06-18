import React, { useState } from "react";

// Persist gate (pivot §8): label + tags, then Save (write to MongoDB + ChromaDB) or Skip.
export default function PersistGate({ onSave, busy, receipt }) {
  const [label, setLabel] = useState("order_flow_v2");
  const [tags, setTags] = useState("order, generated");
  const [dismissed, setDismissed] = useState(false);

  if (receipt) {
    return (
      <section className="bg-green-50 rounded-xl border border-green-200 p-4 my-4 text-sm">
        ✅ Saved <b>{receipt.label}</b> — {receipt.rows} rows
        {receipt.chroma_indexed ? ", indexed in ChromaDB" : ""}.
        <div className="text-xs text-green-700 mt-1 font-mono break-all">{receipt.location}</div>
        <div className="text-xs text-slate-500 mt-1">Re-run with the same fields to see it reused via mongo_lookup.</div>
      </section>
    );
  }
  if (dismissed) return null;

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-4 my-4">
      <h2 className="text-sm font-semibold mb-2">Save dataset for reuse?</h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="block text-xs text-slate-500 mb-0.5">Label</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)}
                 className="rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="text-sm flex-1 min-w-[12rem]">
          <span className="block text-xs text-slate-500 mb-0.5">Tags (comma-separated)</span>
          <input value={tags} onChange={(e) => setTags(e.target.value)}
                 className="w-full rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <button onClick={() => onSave({ label, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) })}
                disabled={busy}
                className="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40">
          {busy ? "Saving…" : "💾 Save to MongoDB"}
        </button>
        <button onClick={() => setDismissed(true)} className="text-sm text-slate-500 hover:text-slate-700">Skip</button>
      </div>
    </section>
  );
}
