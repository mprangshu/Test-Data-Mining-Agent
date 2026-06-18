import React, { useEffect, useMemo, useState } from "react";
import { downloadCsv, downloadCsvWithSources, downloadJson } from "../download.js";

// Per-row provenance metadata (UI only — never part of the exported CSV).
const SOURCES = {
  input:     { label: "Input",     row: "bg-slate-50",   badge: "bg-slate-200 text-slate-700",   dot: "bg-slate-400" },
  generated: { label: "Generated", row: "bg-indigo-50/60", badge: "bg-indigo-100 text-indigo-700", dot: "bg-indigo-500" },
  fetched:   { label: "Fetched",   row: "bg-emerald-50/60", badge: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
  gathered:  { label: "Gathered",  row: "bg-amber-50/60", badge: "bg-amber-100 text-amber-800",   dot: "bg-amber-500" },
};
const SOURCE_ORDER = ["input", "generated", "fetched", "gathered"];
const PREVIEW = 15;

// Renders the generated dataset with per-row provenance (source colour/badge + legend + filter).
export default function ReportView({ result, onGenerateMore, generating = false }) {
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(() => new Set());
  const { report = {}, final_dataset: rows = [], coverage_gaps: gaps = [], meta = {}, errors = [] } = result || {};

  // Prefer output_rows (carry provenance); fall back to the clean dataset tagged generic.
  const outRows = useMemo(() => {
    if (Array.isArray(result?.output_rows) && result.output_rows.length) return result.output_rows;
    return rows.map((r, i) => ({ fields: r, source: "generated", row_uid: `r${i}` }));
  }, [result, rows]);

  const counts = useMemo(() => {
    const c = {};
    outRows.forEach((r) => { c[r.source] = (c[r.source] || 0) + 1; });
    return c;
  }, [outRows]);

  // Reset selection whenever a new round/result arrives (row_uids change each round).
  useEffect(() => { setSelected(new Set()); }, [result]);

  if (!result) return null;
  const cols = report.columns || (outRows[0] ? Object.keys(outRows[0].fields) : []);
  const filtered = filter === "all" ? outRows : outRows.filter((r) => r.source === filter);
  const preview = filtered.slice(0, PREVIEW);
  const present = SOURCE_ORDER.filter((s) => counts[s]);

  const selectable = typeof onGenerateMore === "function";
  const toggleRow = (uid) => setSelected((s) => {
    const next = new Set(s);
    next.has(uid) ? next.delete(uid) : next.add(uid);
    return next;
  });
  const allFilteredSelected = filtered.length > 0 && filtered.every((r) => selected.has(r.row_uid));
  const toggleAllFiltered = () => setSelected((s) => {
    const next = new Set(s);
    if (allFilteredSelected) filtered.forEach((r) => next.delete(r.row_uid));
    else filtered.forEach((r) => next.add(r.row_uid));
    return next;
  });
  const runGenerateMore = () => {
    const picked = outRows.filter((r) => selected.has(r.row_uid)).map((r) => r.fields);
    if (picked.length) onGenerateMore(picked);
  };

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          Generated dataset{result.round_index ? ` · round ${result.round_index}` : ""}
        </h2>
        <div className="flex gap-2">
          <button onClick={() => downloadCsv(result)}
                  className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
            ⬇ Download CSV
          </button>
          <button onClick={() => downloadJson(result)}
                  className="rounded-lg border border-accent px-3 py-1.5 text-sm font-medium text-accent hover:bg-indigo-50">
            ⬇ JSON
          </button>
        </div>
      </div>

      <p className="text-[11px] text-slate-400 -mt-3">
        CSV = clean test data (original columns only).{" "}
        <button onClick={() => downloadCsvWithSources(result)} className="underline hover:text-slate-600">
          CSV + sources (debug)
        </button>
      </p>

      {report.summary && <div className="rounded-lg bg-indigo-50 p-3 text-sm font-medium">{report.summary}</div>}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Rows" value={report.row_count ?? rows.length} />
        <Stat label="Fields" value={meta.fields ?? cols.length} />
        <Stat label="Coverage gaps" value={gaps.length} />
        <Stat label="Gaps filled" value={(report.gaps_filled_fields || []).length} />
      </div>

      {/* Provenance legend + filter — clicking a chip filters the table by source. */}
      {present.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500 mr-1">Source:</span>
          <Chip active={filter === "all"} onClick={() => setFilter("all")}
                dot="bg-slate-400" label={`All ${outRows.length}`} />
          {present.map((s) => (
            <Chip key={s} active={filter === s} onClick={() => setFilter(s)}
                  dot={SOURCES[s].dot} label={`${SOURCES[s].label} ${counts[s]}`} />
          ))}
          <span className="text-[11px] text-slate-400 ml-auto">source is on-screen only — not in the CSV</span>
        </div>
      )}

      {/* Iterative loop: pick rows → seed a fresh grounded round (replace). */}
      {selectable && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 px-3 py-2">
          <span className="text-xs text-slate-600">
            {selected.size} row{selected.size === 1 ? "" : "s"} selected
            {filter !== "all" ? ` (filter: ${filter})` : ""}
          </span>
          <button onClick={runGenerateMore} disabled={selected.size === 0 || generating}
                  className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed">
            {generating ? "Generating…" : "↻ Generate more from selected"}
          </button>
          {selected.size > 0 && (
            <button onClick={() => setSelected(new Set())} className="text-xs text-slate-500 hover:text-slate-700">
              clear selection
            </button>
          )}
          <span className="text-[11px] text-slate-400 ml-auto">
            selected rows seed the next round; everything else is regenerated
          </span>
        </div>
      )}

      {preview.length > 0 && (
        <div className="overflow-x-auto">
          <table className="text-xs border-collapse">
            <thead className="text-left text-slate-500 border-b">
              <tr>
                {selectable && (
                  <th className="py-1.5 px-2">
                    <input type="checkbox" checked={allFilteredSelected} onChange={toggleAllFiltered}
                           title="Select all rows in the current filter" />
                  </th>
                )}
                <th className="py-1.5 px-2">source</th>
                {cols.map((c) => <th key={c} className="py-1.5 px-2 whitespace-nowrap">{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {preview.map((r) => {
                const meta_ = SOURCES[r.source] || SOURCES.generated;
                const checked = selected.has(r.row_uid);
                return (
                  <tr key={r.row_uid}
                      className={`border-b border-slate-100 ${meta_.row} ${checked ? "ring-1 ring-inset ring-accent/40" : ""}`}>
                    {selectable && (
                      <td className="py-1 px-2">
                        <input type="checkbox" checked={checked} onChange={() => toggleRow(r.row_uid)} />
                      </td>
                    )}
                    <td className="py-1 px-2">
                      <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${meta_.badge}`}>
                        {meta_.label}
                      </span>
                    </td>
                    {cols.map((c) => (
                      <td key={c} className="py-1 px-2 whitespace-nowrap font-mono">{String(r.fields[c] ?? "")}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filtered.length > preview.length && (
            <p className="text-xs text-slate-400 mt-1">
              … {filtered.length - preview.length} more {filter === "all" ? "" : `${filter} `}rows in the download.
            </p>
          )}
        </div>
      )}

      {(report.recommendations || []).length > 0 && (
        <div>
          <h3 className="font-medium mb-2">Recommendations</h3>
          <ul className="list-disc list-inside text-sm space-y-1 text-slate-700">
            {report.recommendations.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {errors.length > 0 && (
        <div className="space-y-1">
          {errors.map((e, i) => <p key={i} className="text-xs rounded bg-red-50 text-red-800 px-3 py-1.5">❌ {e}</p>)}
        </div>
      )}
    </section>
  );
}

function Chip({ active, onClick, dot, label }) {
  return (
    <button onClick={onClick}
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium border transition
              ${active ? "border-accent bg-indigo-50 text-accent" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      {label}
    </button>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3 text-center">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
