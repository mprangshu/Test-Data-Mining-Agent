import React, { useRef, useState } from "react";

// Two input buckets (pivot §8): required Test cases + optional Test results, plus an optional
// paste box for a single test-case file. Multi-file selection accumulates and dedupes.
export default function InputPanel({
  testCases, setTestCases,
  results, setResults,
  text, setText, format, setFormat,
}) {
  const [showPaste, setShowPaste] = useState(false);
  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 space-y-4">
      <FileBucket
        label="Test cases"
        hint="user stories / test-case sheets — .xlsx, .csv, .json, .txt (Gherkin). Required."
        accept=".xlsx,.csv,.json,.txt"
        exts={/\.(xlsx|csv|json|txt)$/i}
        files={testCases}
        setFiles={setTestCases}
      />
      <FileBucket
        label="Test results (optional)"
        hint="JUnit/TestNG .xml or Playwright .json — drives coverage gaps + realistic seeds."
        accept=".xml,.json"
        exts={/\.(xml|json)$/i}
        files={results}
        setFiles={setResults}
      />

      <div>
        <button onClick={() => setShowPaste((v) => !v)} className="text-xs text-accent hover:underline">
          {showPaste ? "− Hide paste" : "+ Or paste a test case"}
        </button>
        {showPaste && (
          <div className="mt-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste a CSV / JSON / Gherkin test case…"
              className="w-full h-28 rounded-lg border border-slate-300 p-2 font-mono text-xs focus:border-accent focus:ring-1 focus:ring-accent outline-none"
            />
            <label className="mt-1 flex items-center gap-2 text-sm text-slate-600">
              Format:
              <select value={format} onChange={(e) => setFormat(e.target.value)}
                      className="rounded border border-slate-300 px-2 py-1 text-sm">
                <option value="auto">auto</option>
                <option value="csv">csv</option>
                <option value="json">json</option>
                <option value="txt">gherkin/txt</option>
              </select>
            </label>
          </div>
        )}
      </div>
    </section>
  );
}

function FileBucket({ label, hint, accept, exts, files, setFiles }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const add = (incoming) => {
    const allowed = Array.from(incoming).filter((f) => exts.test(f.name));
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      const merged = [...prev];
      for (const f of allowed) {
        const k = `${f.name}:${f.size}`;
        if (!seen.has(k)) { seen.add(k); merged.push(f); }
      }
      return merged;
    });
  };

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="font-medium text-sm">{label}</h3>
        {files.length > 0 && (
          <button onClick={() => setFiles([])} className="text-xs text-slate-400 hover:text-red-600">clear</button>
        )}
      </div>
      <input ref={inputRef} type="file" multiple accept={accept} className="hidden"
             onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); add(e.dataTransfer.files); }}
        onClick={() => inputRef.current?.click()}
        className={`flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed p-5 cursor-pointer transition ${
          dragging ? "border-accent bg-indigo-50" : "border-slate-300 hover:border-slate-400"
        }`}
      >
        <span className="text-2xl">⬆</span>
        <p className="text-xs text-slate-600">Drag &amp; drop or <span className="text-accent font-medium">browse</span></p>
        <p className="text-[11px] text-slate-400 text-center">{hint}</p>
      </div>
      {files.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm">
          {files.map((f, i) => (
            <li key={`${f.name}:${i}`} className="flex justify-between items-center rounded bg-slate-50 px-3 py-1">
              <span className="truncate">{f.name}</span>
              <span className="flex items-center gap-2">
                <span className="text-slate-400 text-xs">{(f.size / 1024).toFixed(1)} KB</span>
                <button onClick={() => setFiles((p) => p.filter((_, j) => j !== i))}
                        className="text-slate-400 hover:text-red-600" title="remove">✕</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
