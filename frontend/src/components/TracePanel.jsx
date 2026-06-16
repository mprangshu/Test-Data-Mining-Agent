import React from "react";

// Live node-by-node view of the LangGraph run (demo-overview §2.3).
// `trace` is the list of completed node events; `running` shows the spinner row while streaming.
export default function TracePanel({ trace, running }) {
  if (!trace.length && !running) return null;

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 my-4">
      <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">
        Agent trace
      </h2>
      <ul className="space-y-1.5 font-mono text-xs">
        {trace.map((e, i) => (
          <li key={i}>
            <div className="flex items-center gap-2">
              <span className="text-green-600">✓</span>
              <span className="font-semibold w-40 truncate">{e.node}</span>
              <span className="text-slate-500 flex-1 truncate">{e.summary}</span>
              <span className="text-slate-400 tabular-nums">{e.elapsed_ms} ms</span>
            </div>
            {(e.gaps || []).map((g, j) => (
              <div key={`g${j}`} className="ml-6 text-amber-700">⚠ {g}</div>
            ))}
            {(e.errors || []).map((er, j) => (
              <div key={`e${j}`} className="ml-6 text-red-700">✗ {er}</div>
            ))}
          </li>
        ))}
        {running && (
          <li className="flex items-center gap-2 text-accent">
            <span className="animate-pulse">◐</span>
            <span className="italic">running…</span>
          </li>
        )}
      </ul>
    </section>
  );
}
