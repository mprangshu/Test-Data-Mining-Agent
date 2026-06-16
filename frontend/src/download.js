// Client-side report export: JSON (raw agent output) + Markdown (shareable).

function triggerDownload(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadJson(result) {
  triggerDownload("test-data-mining-report.json", JSON.stringify(result, null, 2), "application/json");
}

export function downloadMarkdown(result) {
  triggerDownload("test-data-mining-report.md", toMarkdown(result), "text/markdown");
}

function toMarkdown(result) {
  const { meta = {}, suite_health: h, flaky_findings = [], failure_clusters = [], coverage_findings = [], report = {}, gaps = [], errors = [] } = result || {};
  const flaky = flaky_findings.filter((f) => f.verdict === "flaky");
  const lines = [];

  lines.push("# Test Data Mining Report", "");
  lines.push(`- Source: **${meta.source ?? "?"}** · Runs: **${meta.runs ?? "?"}** · Results parsed: **${meta.results_parsed ?? "?"}** · Autonomy: **${meta.autonomy ?? "?"}**`, "");
  if (report?.summary) lines.push(`> ${report.summary}`, "");
  if ((report?.priorities || []).length) {
    lines.push("## Prioritised findings", "");
    report.priorities.forEach((p) => lines.push(`${p.rank}. [${p.severity.toUpperCase()}] ${p.title} — ${p.detail}`));
    lines.push("");
  }

  if (h) {
    lines.push("## Suite health", "");
    lines.push(`- Pass rate: **${pct(h.pass_rate)}** · Mean duration: **${h.mean_duration_sec}s** · Flake rate: **${pct(h.flake_rate)}** · Window: **${h.window_runs} runs**`, "");
  }

  lines.push(`## Flaky tests (${flaky.length})`, "");
  if (flaky.length) {
    lines.push("| Test | Score | Pass | Fail | Runs |", "|---|---|---|---|---|");
    flaky.forEach((f) => lines.push(`| ${f.test_id} | ${f.flakiness_score} | ${f.pass_count} | ${f.fail_count} | ${f.runs_observed} |`));
  } else {
    lines.push("_None detected._");
  }
  lines.push("");

  lines.push(`## Failure clusters (${failure_clusters.length})`, "");
  if (failure_clusters.length) {
    failure_clusters.forEach((c) => lines.push(`- **${c.label || c.signature}** ×${c.count}`));
  } else {
    lines.push("_None._");
  }
  lines.push("");

  lines.push("## Coverage gaps", "");
  if (coverage_findings.length) {
    coverage_findings.forEach((c) => lines.push(`- ${c.module}: ${pct(c.coverage_pct / 100)} (${c.status})`));
  } else {
    lines.push("_No coverage data in input._");
  }
  lines.push("");

  const recs = report?.recommendations || [];
  lines.push("## Recommendations", "");
  recs.forEach((r) => lines.push(`- ${r}`));
  lines.push("");

  if (gaps.length || errors.length) {
    lines.push("## Notes", "");
    gaps.forEach((g) => lines.push(`- ⚠️ ${g}`));
    errors.forEach((e) => lines.push(`- ❌ ${e}`));
  }

  return lines.join("\n");
}

function pct(x) {
  return x == null ? "—" : `${(x * 100).toFixed(1)}%`;
}
