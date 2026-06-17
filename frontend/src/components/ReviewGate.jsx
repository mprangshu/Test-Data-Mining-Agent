import React, { useState } from "react";

// Set-based HITL gate (pivot §5): for each field the analyst picks ONE value set (radio),
// or a custom value list, or excludes the field. Submitting resumes the run → final dataset.
export default function ReviewGate({ payload, onSubmit, busy }) {
  const fields = payload?.fields || [];

  const [state, setState] = useState(() =>
    Object.fromEntries(fields.map((f) => [
      f.field_name,
      { include: true, choice: (f.sets[0] && f.sets[0].set_id) || "__custom__", custom: "" },
    ]))
  );

  const upd = (name, patch) => setState((s) => ({ ...s, [name]: { ...s[name], ...patch } }));

  const submit = () => {
    const selections = fields.map((f) => {
      const st = state[f.field_name];
      if (!st.include) return { field_name: f.field_name, include: false };
      if (st.choice === "__custom__") {
        return {
          field_name: f.field_name, include: true,
          custom_values: st.custom.split(",").map((v) => v.trim()).filter(Boolean),
        };
      }
      return { field_name: f.field_name, include: true, chosen_set_id: st.choice };
    });
    onSubmit(selections);
  };

  return (
    <section className="bg-white rounded-xl shadow-sm border border-amber-200 p-4 my-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-amber-800 uppercase tracking-wide">
          ⏸ Review — choose a value set per field ({fields.length})
        </h2>
        <button onClick={submit} disabled={busy}
                className="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40">
          {busy ? "Generating…" : "▶ Generate Final Dataset"}
        </button>
      </div>

      <div className="space-y-3">
        {fields.map((f) => {
          const st = state[f.field_name];
          return (
            <div key={f.field_name} className="rounded-lg border border-slate-200 p-3">
              <div className="flex items-center justify-between mb-2">
                <label className="flex items-center gap-2 text-sm font-medium">
                  <input type="checkbox" checked={st.include}
                         onChange={(e) => upd(f.field_name, { include: e.target.checked })} />
                  <span className="font-mono">{f.field_name}</span>
                  <span className="text-xs text-slate-400">{f.category}</span>
                  {f.gap_flagged && (
                    <span className="rounded bg-amber-100 text-amber-700 px-1.5 py-0.5 text-[10px] font-semibold">⚠ gap</span>
                  )}
                </label>
              </div>

              {st.include && (
                <div className="space-y-1.5 pl-6">
                  {f.sets.map((s) => (
                    <label key={s.set_id} className="flex items-start gap-2 text-sm cursor-pointer">
                      <input type="radio" name={`set-${f.field_name}`} className="mt-1"
                             checked={st.choice === s.set_id}
                             onChange={() => upd(f.field_name, { choice: s.set_id })} />
                      <span>
                        <span className="font-medium">{s.set_id}</span>
                        <span className="text-xs text-slate-400"> · {s.source} · {s.note}</span>
                        <span className="block font-mono text-xs text-slate-500 truncate">
                          {(s.values || []).slice(0, 4).map((v) => (v === "" ? '""' : String(v))).join(", ")}
                        </span>
                      </span>
                    </label>
                  ))}
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="radio" name={`set-${f.field_name}`}
                           checked={st.choice === "__custom__"}
                           onChange={() => upd(f.field_name, { choice: "__custom__" })} />
                    <span className="text-slate-600">Custom:</span>
                    <input type="text" placeholder="comma,separated,values"
                           value={st.custom}
                           onChange={(e) => upd(f.field_name, { custom: e.target.value, choice: "__custom__" })}
                           className="flex-1 rounded border border-slate-300 px-2 py-0.5 text-xs font-mono" />
                  </label>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
