import React, { useRef, useState } from "react";
import InputPanel from "./components/InputPanel.jsx";
import TracePanel from "./components/TracePanel.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import ReviewGate from "./components/ReviewGate.jsx";
import ReportView from "./components/ReportView.jsx";
import PersistGate from "./components/PersistGate.jsx";
import { mine, resume, persistDataset, generateMore } from "./api.js";

// Human-readable agent-bubble text per streamed node (others are intentionally quiet).
const CHAT_NODE = {
  parse: (s) => `Parsed inputs — ${s}`,
  load_results: (s) => `Read test results — ${s}`,
  mongo_lookup: (s) => `Fetched from MongoDB — ${s}`,
  vector_search: (s) => `Gathered from ChromaDB — ${s}`,
  coverage_gap: (s) => `Detected coverage gaps — ${s}`,
  generate: (s) => `Built candidate value sets — ${s}`,
};

function resultBubble(res) {
  const r = res?.report || {};
  const p = r.provenance || {};
  const parts = ["input", "generated", "fetched", "gathered"].filter((k) => p[k]).map((k) => `${p[k]} ${k}`);
  const rows = r.row_count ?? (res?.final_dataset || []).length;
  return `Generated ${rows} rows` + (parts.length ? ` (${parts.join(" + ")})` : "");
}

export default function App() {
  // inputs
  const [testCases, setTestCases] = useState([]);
  const [results, setResults] = useState([]);
  const [text, setText] = useState("");
  const [format, setFormat] = useState("auto");

  // flow / data
  const [streaming, setStreaming] = useState(false);   // mine + resume (NDJSON)
  const [generating, setGenerating] = useState(false); // generate-more (sync)
  const [persistBusy, setPersistBusy] = useState(false);
  const [error, setError] = useState(null);

  const [events, setEvents] = useState([]);            // completed node events → right trace
  const [paused, setPaused] = useState(false);         // review interrupt active
  const [regenRound, setRegenRound] = useState(null);  // generate-more indicator
  const [chat, setChat] = useState([]);                // left rail bubbles

  const [review, setReview] = useState(null);          // {session, payload}
  const [session, setSession] = useState(null);
  const [result, setResult] = useState(null);
  const [roundIndex, setRoundIndex] = useState(0);
  const [receipt, setReceipt] = useState(null);

  const nextId = useRef(0);
  const push = (role, txt) => setChat((c) => [...c, { id: nextId.current++, role, text: txt }]);

  const hasInput = testCases.length > 0 || text.trim().length > 0;
  const stage = review && !result ? "review" : result ? "report" : "input";

  // Single NDJSON handler — fans out to the trace (node rows) and the chat (summary bubbles).
  const onEvent = (evt) => {
    if (evt.type === "node") {
      setEvents((t) => [...t, evt]);
      const fmt = CHAT_NODE[evt.node];
      if (fmt && evt.summary) push("agent", fmt(evt.summary));
    } else if (evt.type === "interrupt") {
      setSession(evt.session);
      setReview({ session: evt.session, payload: evt.payload });
      setPaused(true);
      const n = (evt.payload?.fields || []).length;
      push("agent", `Ready for review — candidate value sets for ${n} field(s).`);
    } else if (evt.type === "result") {
      setResult(evt);
      setPaused(false);
      push("agent", resultBubble(evt));
    }
  };

  const runMine = async () => {
    setError(null); setResult(null); setReview(null); setReceipt(null);
    setEvents([]); setPaused(false); setRoundIndex(0); setChat([]);
    nextId.current = 0;
    const tc = testCases.length, rs = results.length;
    push("user", tc || rs
      ? `Uploaded ${tc} test-case file(s)` + (rs ? ` + ${rs} results file(s)` : "")
      : "Pasted a test case");
    setStreaming(true);
    try {
      await mine({ testCases, results, text, format }, onEvent);
    } catch (e) {
      setError(e.message || "Mining failed");
      push("agent", `⚠ ${e.message || "Mining failed"}`);
    } finally {
      setStreaming(false);
    }
  };

  const submitReview = async (selections) => {
    const sess = review.session;
    const inc = selections.filter((s) => s.include);
    const sample = inc.slice(0, 3)
      .map((s) => `${s.field_name}→${s.chosen_set_id || (s.custom_values ? "custom" : "?")}`)
      .join(", ");
    push("user", `Selected value sets for ${inc.length} field(s)` + (sample ? `: ${sample}${inc.length > 3 ? ", …" : ""}` : ""));
    // Keep `review` set (gate stays visible in a busy state) until the result arrives and flips the
    // stage to report — clearing it now would briefly bounce the middle back to the Input stage.
    setPaused(false); setStreaming(true); setError(null);
    try {
      await resume(sess, selections, onEvent);
    } catch (e) {
      setError(e.message || "Resume failed");
      push("agent", `⚠ ${e.message || "Resume failed"}`);
    } finally {
      setStreaming(false);
    }
  };

  const runGenerateMore = async (rows) => {
    push("user", `Generate more from ${rows.length} selected row(s)`);
    setGenerating(true); setRegenRound((roundIndex || 0) + 1); setError(null); setReceipt(null);
    try {
      const r = await generateMore(session, rows);
      setResult(r);
      setRoundIndex(r.round_index || 0);
      if (r.round_index) push("divider", `Round ${r.round_index}`);
      push("agent", resultBubble(r));
    } catch (e) {
      setError(e.message || "Generate-more failed");
      push("agent", `⚠ ${e.message || "Generate-more failed"}`);
    } finally {
      setGenerating(false); setRegenRound(null);
    }
  };

  const saveDataset = async ({ label, tags }) => {
    setPersistBusy(true); setError(null);
    push("user", `Save dataset as "${label}"`);
    try {
      const r = await persistDataset(session, { save: true, label, tags });
      setReceipt(r.receipt);
      push("agent", `Saved ${r.receipt?.label} — ${r.receipt?.rows} rows${r.receipt?.chroma_indexed ? ", indexed in ChromaDB" : ""}.`);
    } catch (e) {
      setError(e.message || "Save failed");
      push("agent", `⚠ ${e.message || "Save failed"}`);
    } finally {
      setPersistBusy(false);
    }
  };

  const clearAll = () => {
    setTestCases([]); setResults([]); setText("");
    setEvents([]); setReview(null); setSession(null); setResult(null);
    setError(null); setReceipt(null); setPaused(false); setRoundIndex(0);
    setChat([]); nextId.current = 0;
  };

  const stageLabel = { input: "Input", review: "Review", report: "Report" }[stage];

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-ink">
      {/* Slim app header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4">
        <div className="flex items-baseline gap-3">
          <h1 className="text-sm font-bold">Test Data Mining Agent</h1>
          <span className="text-xs text-slate-400">mine · generate · review · export</span>
        </div>
        <div className="flex items-center gap-3">
          <StageIndicator stage={stage} label={stageLabel} round={roundIndex} />
          <button onClick={clearAll} className="text-xs text-slate-500 hover:text-slate-700">Clear</button>
        </div>
      </header>

      {/* Three-column shell: chat (22%) · work (56%) · trace (22%) */}
      <div className="grid min-h-0 flex-1 grid-cols-[22%_56%_22%]">
        <aside className="min-h-0 overflow-y-auto border-r border-slate-200 bg-white">
          <ChatPanel messages={chat} />
        </aside>

        <main className="min-h-0 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-3xl space-y-4">
            {error && (
              <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">⚠ {error}</div>
            )}

            {stage === "input" && (
              <section className="space-y-4">
                <StageHeading title="1 · Provide inputs"
                  subtitle="Upload test cases (+ optional results), or paste a test case, then mine." />
                <InputPanel
                  testCases={testCases} setTestCases={setTestCases}
                  results={results} setResults={setResults}
                  text={text} setText={setText} format={format} setFormat={setFormat}
                />
                <button onClick={runMine} disabled={!hasInput || streaming}
                        className="w-full rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40">
                  {streaming ? "Mining…" : "▶ Mine & Generate"}
                </button>
              </section>
            )}

            {stage === "review" && (
              <section className="space-y-4">
                <StageHeading title="2 · Review — choose a value set per field"
                  subtitle="Pick one candidate set per field (or exclude it), then generate the dataset." />
                <ReviewGate payload={review.payload} onSubmit={submitReview} busy={streaming} />
              </section>
            )}

            {stage === "report" && (
              <section className="space-y-4">
                <StageHeading title="3 · Dataset — provenance, select & export"
                  subtitle="Rows colour-coded by source. Select rows to generate more, download the clean CSV, or save." />
                <ReportView result={result} onGenerateMore={session ? runGenerateMore : undefined} generating={generating} />
                {session && <PersistGate onSave={saveDataset} busy={persistBusy} receipt={receipt} />}
              </section>
            )}
          </div>
        </main>

        <aside className="min-h-0 overflow-y-auto border-l border-slate-200 bg-white">
          <TracePanel events={events} streaming={streaming} paused={paused} regenRound={regenRound} />
        </aside>
      </div>
    </div>
  );
}

function StageIndicator({ stage, label, round }) {
  const steps = ["input", "review", "report"];
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {steps.map((s, i) => (
        <React.Fragment key={s}>
          {i > 0 && <span className="text-slate-300">›</span>}
          <span className={s === stage ? "font-semibold text-accent" : "text-slate-400"}>
            {{ input: "Input", review: "Review", report: "Report" }[s]}
          </span>
        </React.Fragment>
      ))}
      {round > 0 && <span className="ml-1 rounded bg-indigo-50 px-1.5 py-0.5 font-medium text-accent">round {round}</span>}
    </div>
  );
}

function StageHeading({ title, subtitle }) {
  return (
    <div>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="text-xs text-slate-500">{subtitle}</p>
    </div>
  );
}
