import React from "react";
import { downloadJson, downloadMarkdown } from "../download.js";

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

export default function ReportView({ result }) {
  if (!result) return null;
  const {
    meta = {}, suite_health: health, flaky_findings = [],
    failure_clusters = [], coverage_findings = [], report = {},
    gaps = [], errors = [],
  } = result;

  const flaky = flaky_findings.filter((f) => f.verdict === "flaky");
  const recommendations = report?.recommendations || [];
  const priorities = report?.priorities || [];

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Report</h2>
        <div className="flex gap-2">
          <button
            onClick={() => downloadJson(result)}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            ⬇ Download JSON
          </button>
          <button
            onClick={() => downloadMarkdown(result)}
            className="rounded-lg border border-accent px-3 py-1.5 text-sm font-medium text-accent hover:bg-indigo-50"
          >
            ⬇ Markdown
          </button>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Source <b>{meta.source}</b> · {meta.runs} run(s) · {meta.results_parsed} results parsed · autonomy <b>{meta.autonomy}</b>
      </p>

      {(gaps.length > 0 || errors.length > 0) && (
        <div className="space-y-1">
          {gaps.map((g, i) => (
            <p key={`g${i}`} className="text-xs rounded bg-amber-50 text-amber-800 px-3 py-1.5">⚠️ {g}</p>
          ))}
          {errors.map((e, i) => (
            <p key={`e${i}`} className="text-xs rounded bg-red-50 text-red-800 px-3 py-1.5">❌ {e}</p>
          ))}
        </div>
      )}

      {report?.summary && (
        <div className="rounded-lg bg-indigo-50 text-ink p-3 text-sm font-medium">{report.summary}</div>
      )}

      {priorities.length > 0 && (
        <div>
          <h3 className="font-medium mb-2">Prioritised findings ({priorities.length})</h3>
          <ol className="space-y-1.5">
            {priorities.map((p) => (
              <li key={p.rank} className="flex items-start gap-2 text-sm">
                <SevBadge sev={p.severity} />
                <span><b>{p.title}</b> — <span className="text-slate-500">{p.detail}</span></span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {health && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Pass rate" value={pct(health.pass_rate)} />
          <Stat label="Mean duration" value={`${health.mean_duration_sec}s`} />
          <Stat label="Flake rate" value={pct(health.flake_rate)} />
          <Stat label="Window" value={`${health.window_runs} runs`} />
        </div>
      )}

      <div>
        <h3 className="font-medium mb-2">Flaky tests ({flaky.length})</h3>
        {flaky.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-slate-500 border-b">
                <tr>
                  <th className="py-1.5 pr-2">Test</th>
                  <th className="py-1.5 px-2">Score</th>
                  <th className="py-1.5 px-2">Pass</th>
                  <th className="py-1.5 px-2">Fail</th>
                  <th className="py-1.5 px-2">Runs</th>
                </tr>
              </thead>
              <tbody>
                {flaky.map((f) => (
                  <tr key={f.test_id} className="border-b border-slate-100">
                    <td className="py-1.5 pr-2 font-mono text-xs">{f.test_id}</td>
                    <td className="py-1.5 px-2">
                      <span className="inline-block rounded bg-indigo-100 text-accent px-1.5 py-0.5 text-xs font-semibold">
                        {f.flakiness_score}
                      </span>
                    </td>
                    <td className="py-1.5 px-2">{f.pass_count}</td>
                    <td className="py-1.5 px-2">{f.fail_count}</td>
                    <td className="py-1.5 px-2">{f.runs_observed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No flaky tests detected.</Empty>
        )}
      </div>

      <div>
        <h3 className="font-medium mb-2">Failure clusters ({failure_clusters.length})</h3>
        {failure_clusters.length ? (
          <ul className="space-y-2">
            {failure_clusters.map((c) => (
              <li key={c.cluster_id} className="rounded-lg bg-slate-50 p-3">
                <div className="flex justify-between gap-3">
                  <span className="font-medium text-sm">{c.label || c.signature}</span>
                  <span className="text-xs text-slate-500 whitespace-nowrap">×{c.count}</span>
                </div>
                {c.representative_trace && (
                  <pre className="mt-1 text-[11px] text-slate-500 whitespace-pre-wrap">{c.representative_trace}</pre>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No failures clustered.</Empty>
        )}
      </div>

      <div>
        <h3 className="font-medium mb-2">Coverage gaps</h3>
        {coverage_findings.length ? (
          <ul className="text-sm space-y-1">
            {coverage_findings.map((c, i) => (
              <li key={i}>{c.module}: {c.coverage_pct}% — {c.status}</li>
            ))}
          </ul>
        ) : (
          <Empty>No coverage data in input (Phase 2).</Empty>
        )}
      </div>

      <div>
        <h3 className="font-medium mb-2">Recommendations</h3>
        <ul className="list-disc list-inside text-sm space-y-1 text-slate-700">
          {recommendations.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      </div>
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

function SevBadge({ sev }) {
  const cls = {
    high: "bg-red-100 text-red-700",
    medium: "bg-amber-100 text-amber-700",
    low: "bg-slate-100 text-slate-600",
  }[sev] || "bg-slate-100 text-slate-600";
  return (
    <span className={`mt-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}>
      {sev}
    </span>
  );
}

function Empty({ children }) {
  return <p className="text-sm text-slate-400 italic">{children}</p>;
}
