// Client-side export of the generated dataset: CSV (primary) + JSON (secondary).

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

function csvEscape(v) {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function downloadCsv(result) {
  const rows = result?.final_dataset || [];
  if (!rows.length) return;
  const cols = result?.report?.columns || Object.keys(rows[0]);
  const lines = [cols.join(",")];
  rows.forEach((r) => lines.push(cols.map((c) => csvEscape(r[c])).join(",")));
  triggerDownload("test-data.csv", lines.join("\n"), "text/csv");
}

export function downloadJson(result) {
  triggerDownload("test-data-mining-result.json", JSON.stringify(result, null, 2), "application/json");
}
