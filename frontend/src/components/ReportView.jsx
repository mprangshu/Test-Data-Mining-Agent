import React from "react";
import { downloadCsv, downloadJson } from "../download.js";

// Renders the generated dataset (CSV-oriented preview) + coverage/source summary + downloads.
export default function ReportView({ result }) {
  if (!result) return null;
  const { report = {}, final_dataset: rows = [], coverage_gaps: gaps = [], meta = {}, errors = [] } = result;
  const cols = report.columns || (rows[0] ? Object.keys(rows[0]) : []);
  const preview = rows.slice(0, 12);

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Generated dataset</h2>
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

      {report.summary && <div className="rounded-lg bg-indigo-50 p-3 text-sm font-medium">{report.summary}</div>}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Rows" value={report.row_count ?? rows.length} />
        <Stat label="Fields" value={meta.fields ?? cols.length} />
        <Stat label="Coverage gaps" value={gaps.length} />
        <Stat label="Gaps filled" value={(report.gaps_filled_fields || []).length} />
      </div>

      {report.source_mix_pct && (
        <p className="text-xs text-slate-500">
          Source mix:{" "}
          {Object.entries(report.source_mix_pct).map(([k, v]) => `${k} ${v}%`).join(" · ")}
        </p>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="text-xs border-collapse">
            <thead className="text-left text-slate-500 border-b">
              <tr>{cols.map((c) => <th key={c} className="py-1.5 px-2 whitespace-nowrap">{c}</th>)}</tr>
            </thead>
            <tbody>
              {preview.map((r, i) => (
                <tr key={i} className="border-b border-slate-100">
                  {cols.map((c) => <td key={c} className="py-1 px-2 whitespace-nowrap font-mono">{String(r[c] ?? "")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > preview.length && (
            <p className="text-xs text-slate-400 mt-1">… {rows.length - preview.length} more rows in the download.</p>
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

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3 text-center">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
