# IMPROVEMENT.md — Fixing the TDM Agent Output (code-accurate, v2)

> **Read before editing.** Written against the actual node source. The agent's job, stated
> precisely:
>
> **Schema-agnostic.** Whatever columns the uploaded file has — any count, any names — the
> output has the *same* columns. `tdm_demo_output.csv` is a **shape reference only**, never a
> fixed schema. No column name is ever hardcoded.
>
> **Additive, never subtractive.** Output = **all original uploaded rows, unchanged** + **new
> generated rows appended**. The agent never deletes, dedupes, or drops data.
>
> **Fill gaps, don't optimize.** The goal is to *generate more meaningful test data* — fill the
> gaps with new rows. It is **not** an optimizer: it must not clean, dedupe, "improve," or
> compress the uploaded data. Old data stays; new data is added on top.
>
> **Always larger (hard rule).** `output_rows > input_rows`, guaranteed, for every input. This
> is the firm requirement. (A bigger target like ~3x is *optional* and tunable — see
> `EXPANSION_FACTOR` — but the only thing that must always hold is: more rows out than in.)
>
> **Coherent.** New rows are kept internally consistent by the **LLM at generation time**
> (no hardcoded per-schema rules).

---

## 0. Root-cause summary (what actually happened)

Input 50 rows -> output 6 rows, all `data_category: generated`, discount codes `sample_value_*`.

| # | Symptom | Real cause | Location |
|---|---------|-----------|----------|
| 1 | Only 6 rows (shrank!) | Row count = longest candidate set, capped at 6; originals dropped | `synthesise.py` `_MAX_ROWS`/`n=` lines + `generate.py` `_MAX=6` |
| 2 | `data_category: generated` | Scenario type discarded; hardcoded label | `synthesise.py` row-build loop |
| 3 | `scenario_tag: generated_001` | Hardcoded counter, not real tag | `synthesise.py` row-build loop |
| 4 | `sample_value_1/2/3` | Field names absent from `_VALID` -> fall through to `_GENERIC` placeholders | `generate.py` `_VALID`/`_GENERIC` |
| 5 | free@35000, premium@9.99 | Columns zipped by index; no coherence | `synthesise.py` row-build loop |
| 6 | Originals discarded | `synthesise` builds only from candidate sets; never carries input rows through | `synthesise.py` (no passthrough of raw input) |
| 7 | Seed never helps | Fixtures hardcode one schema | `generate_fixtures.py` `CSV_PATH`/`REUSED_FIELDS` |

The pipeline is wired correctly. The defects sit in **`synthesise.py`** (assembler) and
**`generate.py`'s hardcoded value pools**, plus a fixtures schema mismatch.

---

## 1. Defect 1 + 6 — output shrinks and drops the originals (headline bug)

**What's wrong.** `synthesise.py`:
```python
_MAX_ROWS = 20
n = min(max((len(v) for v, _s, _c in chosen.values()), default=0), _MAX_ROWS)
for i in range(n):
    row = {name: vals[i % len(vals)] for name, (vals, _s, _c) in chosen.items()}
```
Row count = length of the longest candidate set, and `generate.py` caps each set at `_MAX = 6`,
so `n = min(6, 20) = 6` — always. Worse, the output is built **only** from candidate sets; the
original uploaded rows are never included. So the agent both caps *and* discards.

**Why it's wrong.** The agent must be additive and always larger. This does the opposite.

**How to fix.** Output = **original rows (verbatim)** + **new generated rows**.

```python
# config (thread through initial_state / parse)
# HARD RULE: total output must be > input. EXPANSION_FACTOR is just an OPTIONAL bigger target.
EXPANSION_FACTOR = 3            # optional: aim for ~3x input; tunable. The must-hold rule is > input.

def synthesise(state, llm=None):
    original_rows = state.get("input_rows", [])        # full raw rows from parse(), unchanged
    columns       = state.get("input_columns", [])     # exact uploaded column list/order
    input_n       = len(original_rows)

    # add at least 1 new row (hard rule: > input); default aims higher via EXPANSION_FACTOR
    new_target = max(1, (EXPANSION_FACTOR - 1) * max(input_n, 1))

    new_rows = build_new_rows(state, columns, new_target, llm)   # sections 2-4

    final_dataset = original_rows + new_rows           # ADDITIVE: originals first, then new
    assert len(final_dataset) > input_n, "REGRESSION: output not larger than input"
    return {"final_dataset": final_dataset, "report": {...}}
```

Key points:
- **Originals pass through untouched** (don't dedupe, don't reformat, don't "optimize").
- **Columns come from the input**, not from any hardcoded list — see section 3.
- Raise/remove `generate.py` `_MAX = 6` (e.g. 24) so sets have enough distinct values.
- The hard guard is `len(final_dataset) > input_n`; since originals are always included plus at
  least one new row, the output can never be smaller than — or equal to — the input.

---

## 2. Defect 2 + 3 — honest tagging on the NEW rows (only if those columns exist)

> **Scope note.** Scenario types (valid/boundary/negative/edge) come from the *existing* design,
> not from a hard requirement. The core goal is just "more meaningful data filling gaps." So
> scenario tagging is **secondary to the schema-agnostic rule**: only ever touch
> `scenario_tag` / `data_category` **if the uploaded file actually has those columns**. If it
> doesn't, skip all of this — never invent those columns.

**What's wrong.** Every row hardcodes:
```python
row["scenario_tag"] = f"generated_{i + 1:03d}"
row["data_category"] = "generated"
```
The `scenario_coverage` from each `CandidateSet` is ignored; all rows collapse to `generated`.
Worse, these columns are written even when the input never had them.

**Why it's wrong.** When the input *does* carry a scenario/category column, collapsing everything
to `generated` throws away the coverage signal that makes the new data meaningful. When the input
*doesn't*, writing these columns violates the schema-agnostic rule.

**How to fix.** When (and only when) `data_category` / `scenario_tag` exist in the input columns,
generate new rows **per scenario type** and tag them honestly:
```python
has_cat = "data_category" in columns
has_tag = "scenario_tag" in columns
for stype in ["valid", "boundary", "negative", "edge"]:
    for j in range(rows_for(stype)):       # weight toward coverage_gaps in Mode A; even in Mode B
        row = make_row(columns, stype, llm) # section 4
        if has_tag: row["scenario_tag"]  = f"{stype}_{j+1:03d}"
        if has_cat: row["data_category"] = stype
```
If neither column exists, just generate `new_target` meaningful rows (LLM-coherent, gap-filling)
without any scenario tagging. The schema-agnostic rule always wins.

---

## 3. Schema-agnostic columns (no hardcoding, ever)

**What's wrong.** `generate.py` carries order-flow tables (`_VALID` has `order_id`,
`order_total`, ...). Any field not in the table -> `_GENERIC` -> `sample_value_*`. This bakes in
one schema.

**Why it's wrong.** The agent must handle *any* uploaded schema: 13 or 50 columns, any names.

**How to fix.**
- The **column set is taken from the uploaded file** (`state["input_columns"]`), preserved in
  order. Every uploaded column appears in every output row — including columns the generator has
  never seen.
- **Delete the hardcoded `_VALID/_NEGATIVE/_BOUNDARY/_EDGE/_GENERIC` schema tables** as the
  primary path. Value generation becomes **per-column, driven by what the data shows**:
  1. Real values for that column from `seed_values` / `existing_data` / the original rows
     (these are the best examples).
  2. The LLM, prompted with the column name + sample real values, to produce more like them
     (section 4).
  3. A deterministic fallback (faker-style by inferred type) only if the LLM is unavailable —
     and even then produce *plausible* values, never `sample_value_*`.
- **Delete `_GENERIC["valid"] = ["sample_value_1", ...]`.** Add a placeholder guard that rejects
  `sample_value_*`, `generated_\d+`, `test_*` if they ever appear in seed/existing data.

> The column list and the value generator are independent: unknown column names must still get
> values, just by falling back to LLM/inferred-type generation rather than a lookup table.

---

## 4. Defect 5 — coherence via the LLM (not hardcoded rules)

**What's wrong.** `synthesise` fills each column independently and zips by index, so
`plan_type=free` lands next to `amount=35000`.

**Why it's wrong.** New rows must be internally consistent — but the consistency rules differ per
schema and can't be hardcoded (that would break on a non-subscription upload).

**How to fix.** Generate each **new row as a whole** with the LLM, so cross-field consistency is
handled at generation time:
```python
def make_row(columns, stype, llm):
    prompt = (
        f"Generate ONE realistic test-data row as JSON with EXACTLY these columns: {columns}. "
        f"Scenario type: {stype} (valid=happy path; boundary=limits; negative=invalid; edge=unusual). "
        f"Use these real example rows for realism and to infer relationships between columns: "
        f"{sample_real_rows}. Keep the row internally consistent (values across columns must agree). "
        f"Return ONLY a JSON object, no prose."
    )
    row = json.loads(llm(prompt))
    return {c: row.get(c, "") for c in columns}   # enforce exact column set
```
- The LLM infers relationships (plan<->price, country<->currency, etc.) **from the example rows**
  — no schema-specific code.
- Generate in **small batches** (e.g. 5 rows/call) for speed; validate each is JSON with the
  right columns; on failure, retry once then fall back to per-column deterministic values.
- **LLM unavailable** (offline/tests): fall back to per-column independent generation seeded by
  real values. Rows may be less coherent, but the agent still runs and still expands — coherence
  is best-effort when there's no LLM.

---

## 5. Mode A / Mode B — both expand; XML only steers the mix

`coverage_gap.py` is already correct: with no `result_signals`, every field x scenario is a gap.

- **Mode A (XML present):** weight the NEW rows toward the scenario types the XML shows untested
  (e.g. boundary/edge), and use passing values as realism seeds. (`generate.py` already builds
  `seed_values` into `gen_A`.)
- **Mode B (no XML):** even spread across the four scenario types. Still `output > input`.

No change to `coverage_gap.py`. The weighting lives in section 2's `rows_for(stype)`.

---

## 6. Fixtures / Mongo seed — schema mismatch

**What's wrong.** `generate_fixtures.py` hardcodes `CSV_PATH = tdm_demo_output.csv` (order-flow)
and `REUSED_FIELDS = [...]`. The demo seeds order data while you feed subscription cases.

**How to fix.**
- Make the source a CLI arg: `--source <file>.csv`. Don't hardcode a schema.
- Derive `REUSED_FIELDS` from the chosen CSV's columns (pick a few to pre-store in Mongo; leave
  the rest as gaps).
- After seeding, assert no `sample_value_*` leaked in.

---

## 7. Exact change list (by file)

**`synthesise.py`** (most important)
- [ ] Output = `state["input_rows"]` (verbatim) **+** new rows. Never drop/dedupe/clean originals.
- [ ] Delete `_MAX_ROWS` and the `n = min(max(...), _MAX_ROWS)` cap.
- [ ] Hard rule: `len(output) > len(input)`. Optional bigger target via `EXPANSION_FACTOR`.
- [ ] Use **input columns** for every row (schema-agnostic); never hardcode or add columns.
- [ ] Tag `scenario_tag`/`data_category` **only if** those columns exist in the input; else skip.
- [ ] Generate rows via the LLM for coherence (section 4); deterministic fallback offline.
- [ ] Guard: `assert len(final_dataset) > len(input_rows)`.

**`generate.py`**
- [ ] Raise `_MAX` (6 -> ~24).
- [ ] Demote/remove hardcoded schema tables; generate per-column from real values + LLM.
- [ ] Delete `_GENERIC["valid"]` `sample_value_*`; add placeholder guard.

**`parse.py`** (needed)
- [ ] Emit `input_rows` (full raw rows) and `input_columns` (exact names/order) into state.
- [ ] Emit `input_row_count` for sizing.

**`generate_fixtures.py`**
- [ ] `--source` arg; derive `REUSED_FIELDS` from it; placeholder assertion.

**No change:** `coverage_gap.py`, `mongo_lookup.py`, `vector_search.py`, `review.py`, `persist.py`.

---

## 8. Acceptance criteria

Run on any uploaded CSV (e.g. `subscription_tests_v2.csv`), Mode A (with XML) and Mode B (without):

| Check | Pass condition |
|---|---|
| Always larger (hard rule) | `output_rows > input_rows` for every input |
| Additive | every original row appears unchanged in the output |
| Not optimized | no dedupe / cleaning / reformatting of original rows |
| Schema-agnostic | output columns == uploaded columns exactly (any count/names), same order |
| Scenario spread | **if** `data_category` exists: new rows span valid/boundary/negative/edge; if it doesn't exist, the column is never added |
| Honest tags | when present, new rows tagged by real scenario, never `generated_NNN` |
| No placeholders | zero `sample_value_*` / `generated_\d+` values |
| Coherence | LLM rows internally consistent (no free@nonzero etc.) when LLM available |
| Mode parity | expands in both modes; XML only shifts the scenario mix |

Extend the golden harness to assert these (especially "every original row present" and
"columns == input columns").

---

## 9. One-paragraph brief for Claude Code

> Make the agent schema-agnostic and additive. **Hard rule: the output must have more rows than
> the input, always** — it is the original uploaded rows (verbatim) PLUS newly generated rows.
> Never drop, dedupe, clean, or "optimize" the originals; the agent fills gaps with new data, it
> does not optimize existing data. A bigger target (~3x via EXPANSION_FACTOR) is optional and
> tunable; the only must-hold is `output > input`. Take the column set from the uploaded file
> (`state["input_columns"]`); every output row has exactly those columns, whatever they are — no
> hardcoded column names, and never add a column the input didn't have. Delete the `_MAX_ROWS`
> cap and the hardcoded `data_category="generated"`/`scenario_tag="generated_NNN"`. Scenario
> tagging is secondary to the schema-agnostic rule: only tag new rows by scenario type **if**
> `data_category`/`scenario_tag` exist in the input; otherwise just add meaningful gap-filling
> rows untagged. Generate each NEW row as a whole via the LLM (prompt it with the input columns +
> a few real example rows so it infers cross-column relationships and stays coherent); fall back
> to per-column deterministic generation when the LLM is unavailable. In `generate.py`, raise the
> `_MAX=6` cap and remove the order-flow `_VALID`/`_GENERIC` tables (source of the
> `sample_value_*` placeholders) in favour of per-column generation from real values + LLM. Have
> `parse.py` put the full raw rows and exact column list into state. Make `generate_fixtures.py`
> take a `--source` CSV instead of hardcoding `tdm_demo_output.csv`. `coverage_gap`,
> `mongo_lookup`, `vector_search`, `review`, `persist` need no changes. Acceptance: output strictly
> larger than input, all originals preserved unchanged, columns match the upload exactly, no
> placeholders, coherent new rows.
