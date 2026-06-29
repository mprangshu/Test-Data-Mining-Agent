import React from "react";

// Right rail: realtime agent trace. Shows every pipeline node in order with a live status icon,
// its one-line summary, and elapsed ms. `events` = completed {type:"node"} events from the stream;
// the next not-yet-done node is shown as running while streaming; `review` shows ⏸ when paused.
const PIPELINE = [
  "parse", "load_results", "mongo_lookup", "vector_search", "coverage_gap",
  "generate", "review", "synthesise", "persist",
];

const ICON = {
  pending: { cls: "text-slate-300", glyph: "○" },
  running: { cls: "text-accent animate-pulse", glyph: "◐" },
  done:    { cls: "text-green-600", glyph: "✓" },
  error:   { cls: "text-red-600", glyph: "✗" },
  paused:  { cls: "text-amber-600", glyph: "⏸" },
};

export default function TracePanel({ events = [], streaming = false, paused = false, regenRound = null }) {
  const byNode = {};
  events.forEach((e) => { byNode[e.node] = e; });
  const runningNode = streaming && !paused ? PIPELINE.find((n) => !byNode[n]) : null;

  return (
    <div className="flex h-full flex-col">
      <h2 className="shrink-0 px-3 pt-3 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Agent trace
      </h2>
      <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4 font-mono text-xs">
        {PIPELINE.map((n) => {
          const e = byNode[n];
          let status = e ? ((e.errors || []).length ? "error" : "done") : "pending";
          if (!e && n === "review" && paused) status = "paused";
          else if (!e && n === runningNode) status = "running";
          const ic = ICON[status];
          return (
            <li key={n} className="rounded px-1.5 py-1 hover:bg-slate-50">
              <div className="flex items-center gap-2">
                <span className={ic.cls}>{ic.glyph}</span>
                <span className={`flex-1 truncate ${status === "pending" ? "text-slate-400" : "font-semibold text-slate-700"}`}>
                  {n}
                </span>
                {e && <span className="tabular-nums text-slate-400">{e.elapsed_ms}ms</span>}
              </div>
              {e?.summary && <div className="ml-6 truncate text-slate-500">{e.summary}</div>}
              {(e?.gaps || []).map((g, j) => <div key={`g${j}`} className="ml-6 truncate text-amber-700">⚠ {g}</div>)}
              {(e?.errors || []).map((er, j) => <div key={`e${j}`} className="ml-6 truncate text-red-700">✗ {er}</div>)}
            </li>
          );
        })}
      </ul>
      {regenRound != null && (
        <div className="shrink-0 border-t border-slate-100 px-3 py-2 text-xs text-accent">
          <span className="mr-1.5 animate-pulse">↻</span>Round {regenRound} regenerating…
        </div>
      )}
    </div>
  );
}
