// Client for the v2 backend (backend/app.py): /mine streams to the review gate, /resume completes.
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function readErrorDetail(resp) {
  const data = await resp.json().catch(() => ({}));
  const detail = data?.detail || `Request failed (${resp.status})`;
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

// Read an NDJSON streaming response, invoking onEvent(evt) per line.
async function consumeNdjson(resp, onEvent) {
  if (!resp.ok) throw new Error(await readErrorDetail(resp));
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const flush = (line) => { const t = line.trim(); if (t) onEvent(JSON.parse(t)); };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) { flush(buf.slice(0, nl)); buf = buf.slice(nl + 1); }
  }
  flush(buf);
}

/**
 * Mine: upload test-case files (+ optional result files) and/or pasted text.
 * Streams {type:"node"} events, then {type:"interrupt", session, payload} at the review gate.
 */
export async function mine({ testCases = [], results = [], text = "", format = "auto" }, onEvent) {
  const body = new FormData();
  testCases.forEach((f) => body.append("test_cases", f, f.name));
  results.forEach((f) => body.append("results", f, f.name));
  if (text && text.trim()) { body.append("text", text); body.append("format", format); }
  const resp = await fetch(`${API_BASE}/mine`, { method: "POST", body });
  await consumeNdjson(resp, onEvent);
}

/** Resume a paused run with the analyst's set selections; streams to {type:"result"}. */
export async function resume(session, reviewSelections, onEvent) {
  const body = new FormData();
  body.append("session", session);
  body.append("review_selections", JSON.stringify(reviewSelections || []));
  const resp = await fetch(`${API_BASE}/resume`, { method: "POST", body });
  await consumeNdjson(resp, onEvent);
}

/** Persist gate: save the session's generated dataset to MongoDB + ChromaDB. */
export async function persistDataset(session, { save, label, tags }) {
  const body = new FormData();
  body.append("session", session);
  body.append("save", save ? "true" : "false");
  body.append("label", label || "");
  body.append("tags", (tags || []).join(","));
  const resp = await fetch(`${API_BASE}/persist`, { method: "POST", body });
  if (!resp.ok) throw new Error(await readErrorDetail(resp));
  return resp.json();
}
