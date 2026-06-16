import React, { useState } from "react";
import InputPanel from "./components/InputPanel.jsx";
import TracePanel from "./components/TracePanel.jsx";
import ReviewGate from "./components/ReviewGate.jsx";
import ReportView from "./components/ReportView.jsx";
import { analyseStream, resumeStream } from "./api.js";

export default function App() {
  const [mode, setMode] = useState("upload");
  const [files, setFiles] = useState([]);
  const [text, setText] = useState("");
  const [format, setFormat] = useState("auto");
  const [autonomy, setAutonomy] = useState("L1");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [trace, setTrace] = useState([]);
  const [review, setReview] = useState(null);   // {session, findings} when paused at L2 gate

  const hasInput = mode === "upload" ? files.length > 0 : text.trim().length > 0;

  // Shared event handler for both the initial stream and the resumed stream.
  const onEvent = (evt) => {
    if (evt.type === "node") setTrace((t) => [...t, evt]);
    else if (evt.type === "interrupt") setReview({ session: evt.session, findings: evt.findings });
    else if (evt.type === "result") setResult(evt);
  };

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setTrace([]);
    setReview(null);
    try {
      await analyseStream({ mode, files, text, format, autonomy }, onEvent);
    } catch (e) {
      setError(e.message || "Analysis failed");
    } finally {
      setLoading(false);
    }
  };

  const submitReview = async (decisions) => {
    const { session } = review;
    setReview(null);
    setLoading(true);
    try {
      await resumeStream(session, decisions, onEvent);
    } catch (e) {
      setError(e.message || "Resume failed");
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    setFiles([]);
    setText("");
    setResult(null);
    setError(null);
    setTrace([]);
    setReview(null);
  };

  return (
    <div className="min-h-full max-w-4xl mx-auto px-4 py-6">
      <header className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold">Test Data Mining Agent</h1>
          <p className="text-xs text-slate-500">Read-only CI quality intelligence — flaky tests, clusters, coverage, trends.</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          Autonomy
          <select
            value={autonomy}
            onChange={(e) => setAutonomy(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="L1">L1 · Assistive</option>
            <option value="L2">L2 · Supervised</option>
            <option value="L3">L3 · Goal-driven</option>
          </select>
        </label>
      </header>

      <InputPanel
        mode={mode} setMode={setMode}
        files={files} setFiles={setFiles}
        text={text} setText={setText}
        format={format} setFormat={setFormat}
      />

      <div className="flex items-center gap-3 my-4">
        <button
          onClick={runAnalysis}
          disabled={!hasInput || loading}
          className="rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? "Analysing…" : "▶ Analyse"}
        </button>
        <button onClick={clearAll} className="text-sm text-slate-500 hover:text-slate-700">
          Clear
        </button>
        {error && <span className="text-sm text-red-600">⚠ {error}</span>}
      </div>

      <TracePanel trace={trace} running={loading && !review} />

      {review && <ReviewGate findings={review.findings} onSubmit={submitReview} busy={loading} />}

      <ReportView result={result} />

      {!result && !error && !loading && trace.length === 0 && (
        <p className="text-center text-sm text-slate-400 mt-10">
          Upload CI test results or paste them, then click Analyse.
        </p>
      )}
    </div>
  );
}
