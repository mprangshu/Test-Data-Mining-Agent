import React, { useRef, useState } from "react";

// Two ways to provide CI data (demo-overview §2.1): upload files or paste text.
export default function InputPanel({
  mode, setMode,
  files, setFiles,
  text, setText,
  format, setFormat,
}) {
  const fileInput = useRef(null);
  const [dragging, setDragging] = useState(false);

  // Accumulate across drops/selections and dedupe by name+size (multi-file uploads).
  const addFiles = (incoming) => {
    const allowed = filterAllowed(Array.from(incoming));
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      const merged = [...prev];
      for (const f of allowed) {
        const key = `${f.name}:${f.size}`;
        if (!seen.has(key)) { seen.add(key); merged.push(f); }
      }
      return merged;
    });
  };

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const onPick = (e) => {
    addFiles(e.target.files);
    e.target.value = ""; // reset so re-selecting the same file fires onChange again
  };

  const tabClass = (active) =>
    `px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition ${
      active ? "border-accent text-accent bg-white" : "border-transparent text-slate-500 hover:text-slate-700"
    }`;

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200">
      <div className="flex gap-1 border-b border-slate-200 px-3 pt-2">
        <button className={tabClass(mode === "upload")} onClick={() => setMode("upload")}>
          Upload files
        </button>
        <button className={tabClass(mode === "paste")} onClick={() => setMode("paste")}>
          Paste text
        </button>
      </div>

      <div className="p-4">
        {mode === "upload" ? (
          <div>
            {/* Hidden input is a SIBLING of the clickable zone — never a descendant — so the
                programmatic .click() can't bubble back into the zone's onClick. */}
            <input
              ref={fileInput}
              type="file"
              multiple
              accept=".xml,.json"
              className="hidden"
              onChange={onPick}
            />
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInput.current?.click()}
              className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 cursor-pointer transition ${
                dragging ? "border-accent bg-indigo-50" : "border-slate-300 hover:border-slate-400"
              }`}
            >
              <span className="text-3xl">⬆</span>
              <p className="text-sm text-slate-600">
                Drag &amp; drop or <span className="text-accent font-medium">browse</span>
              </p>
              <p className="text-xs text-slate-400">
                JUnit/TestNG <code>.xml</code> or Playwright <code>.json</code> · multiple files = multiple runs
              </p>
            </div>

            {files.length > 0 && (
              <div className="mt-3">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs text-slate-500">{files.length} file(s) — {files.length} run(s)</span>
                  <button onClick={() => setFiles([])} className="text-xs text-slate-400 hover:text-red-600">
                    remove all
                  </button>
                </div>
                <ul className="space-y-1 text-sm">
                  {files.map((f, i) => (
                    <li key={`${f.name}:${f.size}:${i}`} className="flex justify-between items-center rounded bg-slate-50 px-3 py-1.5">
                      <span className="truncate">{f.name}</span>
                      <span className="flex items-center gap-3">
                        <span className="text-slate-400">{(f.size / 1024).toFixed(1)} KB</span>
                        <button onClick={() => removeFile(i)} className="text-slate-400 hover:text-red-600" title="remove">✕</button>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste raw JUnit XML or Playwright JSON here…"
              className="w-full h-48 rounded-lg border border-slate-300 p-3 font-mono text-xs focus:border-accent focus:ring-1 focus:ring-accent outline-none"
            />
            <label className="mt-2 flex items-center gap-2 text-sm text-slate-600">
              Format:
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
              >
                <option value="auto">auto</option>
                <option value="junit">junit</option>
                <option value="playwright">playwright</option>
              </select>
            </label>
          </div>
        )}
      </div>
    </section>
  );
}

function filterAllowed(list) {
  return list.filter((f) => /\.(xml|json)$/i.test(f.name));
}
