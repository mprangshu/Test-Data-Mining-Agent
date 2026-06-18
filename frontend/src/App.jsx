import React, { useState } from "react";
import InputPanel from "./components/InputPanel.jsx";
import TracePanel from "./components/TracePanel.jsx";
import ReviewGate from "./components/ReviewGate.jsx";
import ReportView from "./components/ReportView.jsx";
import PersistGate from "./components/PersistGate.jsx";
import { mine, resume, persistDataset } from "./api.js";

export default function App() {
  const [testCases, setTestCases] = useState([]);
  const [results, setResults] = useState([]);
  const [text, setText] = useState("");
  const [format, setFormat] = useState("auto");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [trace, setTrace] = useState([]);
  const [review, setReview] = useState(null);   // {session, payload} at the review gate
  const [session, setSession] = useState(null); // kept for the persist gate
  const [result, setResult] = useState(null);
  const [persistBusy, setPersistBusy] = useState(false);
  const [receipt, setReceipt] = useState(null);

  const hasInput = testCases.length > 0 || text.trim().length > 0;

  const onEvent = (evt) => {
    if (evt.type === "node") setTrace((t) => [...t, evt]);
    else if (evt.type === "interrupt") { setSession(evt.session); setReview({ session: evt.session, payload: evt.payload }); }
    else if (evt.type === "result") setResult(evt);
  };

  const saveDataset = async ({ label, tags }) => {
    setPersistBusy(true);
    try {
      const r = await persistDataset(session, { save: true, label, tags });
      setReceipt(r.receipt);
    } catch (e) {
      setError(e.message || "Save failed");
    } finally {
      setPersistBusy(false);
    }
  };

  const runMine = async () => {
    setLoading(true); setError(null); setResult(null); setTrace([]); setReview(null); setReceipt(null);
    try {
      await mine({ testCases, results, text, format }, onEvent);
    } catch (e) {
      setError(e.message || "Mining failed");
    } finally {
      setLoading(false);
    }
  };

  const submitReview = async (selections) => {
    const { session } = review;
    setReview(null);
    setLoading(true);
    try {
      await resume(session, selections, onEvent);
    } catch (e) {
      setError(e.message || "Resume failed");
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    setTestCases([]); setResults([]); setText("");
    setTrace([]); setReview(null); setSession(null); setResult(null); setError(null); setReceipt(null);
  };

  return (
    <div className="min-h-full max-w-4xl mx-auto px-4 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-bold">Test Data Mining Agent</h1>
        <p className="text-xs text-slate-500">
          Generate accurate test data — mine MongoDB/ChromaDB, fill coverage gaps, choose value sets (HITL), export CSV.
        </p>
      </header>

      <InputPanel
        testCases={testCases} setTestCases={setTestCases}
        results={results} setResults={setResults}
        text={text} setText={setText} format={format} setFormat={setFormat}
      />

      <div className="flex items-center gap-3 my-4">
        <button onClick={runMine} disabled={!hasInput || loading}
                className="rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed">
          {loading ? "Mining…" : "▶ Mine & Generate"}
        </button>
        <button onClick={clearAll} className="text-sm text-slate-500 hover:text-slate-700">Clear</button>
        {error && <span className="text-sm text-red-600">⚠ {error}</span>}
      </div>

      <TracePanel trace={trace} running={loading && !review} />

      {review && !result && (
        <ReviewGate payload={review.payload} onSubmit={submitReview} busy={loading} />
      )}

      <ReportView result={result} />

      {result && session && (
        <PersistGate onSave={saveDataset} busy={persistBusy} receipt={receipt} />
      )}

      {!result && !error && !loading && trace.length === 0 && (
        <p className="text-center text-sm text-slate-400 mt-10">
          Upload test cases (and optionally their result files), then click Mine &amp; Generate.
        </p>
      )}
    </div>
  );
}
