import React, { useState } from "react";

// L2 human-in-the-loop gate (spec §2.2): the analyst confirms/dismisses findings, then
// the run resumes to synthesis. Unchecked items are dismissed and excluded from the report.
export default function ReviewGate({ findings, onSubmit, busy }) {
  const flaky = findings?.flaky || [];
  const clusters = findings?.clusters || [];

  const [keepFlaky, setKeepFlaky] = useState(
    () => Object.fromEntries(flaky.map((f) => [f.test_id, true]))
  );
  const [keepCluster, setKeepCluster] = useState(
    () => Object.fromEntries(clusters.map((c) => [c.cluster_id, true]))
  );

  const submit = () => {
    onSubmit({
      dismissed_flaky: flaky.filter((f) => !keepFlaky[f.test_id]).map((f) => f.test_id),
      dismissed_clusters: clusters.filter((c) => !keepCluster[c.cluster_id]).map((c) => c.cluster_id),
    });
  };

  return (
    <section className="bg-amber-50 rounded-xl shadow-sm border border-amber-200 p-4 my-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-amber-800 uppercase tracking-wide">
          ⏸ Review gate (L2) — confirm findings before the report
        </h2>
        <button
          onClick={submit}
          disabled={busy}
          className="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
        >
          {busy ? "Resuming…" : "✓ Confirm & continue"}
        </button>
      </div>
      <p className="text-xs text-amber-700 mb-3">
        Uncheck anything to dismiss it — dismissed items are excluded from the final report.
      </p>

      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <h3 className="font-medium text-sm mb-1">Flaky tests ({flaky.length})</h3>
          {flaky.length ? (
            <ul className="space-y-1 text-sm">
              {flaky.map((f) => (
                <li key={f.test_id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={!!keepFlaky[f.test_id]}
                    onChange={(e) => setKeepFlaky((s) => ({ ...s, [f.test_id]: e.target.checked }))}
                  />
                  <span className="font-mono text-xs truncate">{f.test_id}</span>
                  <span className="text-slate-400 text-xs whitespace-nowrap">({f.flakiness_score})</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400 italic">None</p>
          )}
        </div>

        <div>
          <h3 className="font-medium text-sm mb-1">Failure clusters ({clusters.length})</h3>
          {clusters.length ? (
            <ul className="space-y-1 text-sm">
              {clusters.map((c) => (
                <li key={c.cluster_id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={!!keepCluster[c.cluster_id]}
                    onChange={(e) => setKeepCluster((s) => ({ ...s, [c.cluster_id]: e.target.checked }))}
                  />
                  <span className="text-xs truncate">{c.label || c.signature}</span>
                  <span className="text-slate-400 text-xs whitespace-nowrap">×{c.count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400 italic">None</p>
          )}
        </div>
      </div>
    </section>
  );
}
