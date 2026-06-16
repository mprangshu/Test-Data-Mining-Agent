// Thin client for the demo backend (backend/app.py).
// Override the base at build time with VITE_API_BASE if the backend runs elsewhere.
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function buildBody({ mode, files = [], text = "", format = "auto", autonomy = "L1" }) {
  const body = new FormData();
  body.append("autonomy", autonomy);
  if (mode === "upload") {
    files.forEach((f) => body.append("files", f, f.name));
  } else {
    body.append("text", text);
    body.append("format", format);
  }
  return body;
}

async function readErrorDetail(resp) {
  const data = await resp.json().catch(() => ({}));
  const detail = data?.detail || `Request failed (${resp.status})`;
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

/** One-shot analysis: returns the full report (no trace). */
export async function analyse(opts) {
  const resp = await fetch(`${API_BASE}/analyse`, { method: "POST", body: buildBody(opts) });
  if (!resp.ok) throw new Error(await readErrorDetail(resp));
  return resp.json();
}

// Read an NDJSON streaming response and invoke onEvent(evt) per line.
// (EventSource can't POST, so we read the response body stream directly.)
async function consumeNdjson(resp, onEvent) {
  if (!resp.ok) throw new Error(await readErrorDetail(resp));
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const flush = (line) => {
    const t = line.trim();
    if (t) onEvent(JSON.parse(t));
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      flush(buf.slice(0, nl));
      buf = buf.slice(nl + 1);
    }
  }
  flush(buf);
}

/**
 * Streaming analysis: invokes onEvent(evt) for each NDJSON event as the graph runs.
 * Events: {type:"node", ...} … then either {type:"result", ...} (L1/L3) or
 * {type:"interrupt", session, findings} (L2 review gate).
 */
export async function analyseStream(opts, onEvent) {
  const resp = await fetch(`${API_BASE}/analyse/stream`, { method: "POST", body: buildBody(opts) });
  await consumeNdjson(resp, onEvent);
}

/** Resume a paused L2 run with the analyst's review decisions; streams to completion. */
export async function resumeStream(session, decisions, onEvent) {
  const body = new FormData();
  body.append("session", session);
  body.append("decisions", JSON.stringify(decisions || {}));
  const resp = await fetch(`${API_BASE}/resume`, { method: "POST", body });
  await consumeNdjson(resp, onEvent);
}
