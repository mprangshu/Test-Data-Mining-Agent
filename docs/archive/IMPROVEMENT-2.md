# IMPROVEMENT-2.md — Coherence & Universality (follow-up)

> **Status:** The structural fixes from `IMPROVEMENT.md` landed. The agent now expands
> (50 -> 150, 3x), preserves all originals verbatim, keeps the schema, and dropped
> `sample_value_*`. **This note is only about the remaining half: the NEW rows are
> incoherent, and the fix must stay schema-agnostic.**
>
> **CRITICAL FRAMING — read first.** The subscription file is **one example schema**. The next
> upload could be loan applications, IoT sensor logs, hospital records, retail orders — **any
> columns, any names, any relationships between columns.** Therefore: **no fix below may hardcode
> column names, value lists, or coherence rules for subscriptions** (no `plan_type`, no
> `country->currency` map, no `free->0.00` rule in code). Every rule must be **inferred at
> runtime from the uploaded data**, never written into the agent. If you find yourself typing a
> subscription field name into the code, stop — that's the bug we're trying to remove.

---

## 0. What's still wrong (measured on `test-data__3_.csv`)

| # | Defect | Evidence in the 100 new rows | Root cause |
|---|--------|------------------------------|-----------|
| 1 | Incoherent rows | 83/100 country/currency mismatches (KR/EUR, GB/AED) | columns still zipped independently, not generated as whole rows |
| 2 | Broken dependencies | 21 `free` plans with non-zero amount (35000, 1999) | no cross-column consistency at all |
| 3 | Placeholder discount codes | `discount_code` = 1, 2, 3, 5 | field still not really generated; symptom renamed from `sample_value_*` |
| 4 | No `valid` rows | new rows are only boundary/negative/edge | over-weighted to gaps; valid generation dropped |
| 5 | Duplicate primary keys | SUB-001 appears 7x | new rows reuse original IDs instead of fresh unique ones |
| 6 | Tag/content mismatch | row tagged `negative` holds valid `trialing` data | scenario label not reflected in the actual values |

All six share **one** root cause: **the new rows are permutations of the original column values
(index-zipped), not freshly generated coherent records.** Fixing that one thing fixes all six —
*provided the fix is data-driven, not subscription-specific.*

---

## 1. The core fix — generate each new row as a coherent whole (schema-agnostic)

Replace the per-column zipping with **whole-row generation**, driven entirely by the uploaded
data. The agent must learn the schema and its relationships from the input itself.

### 1a. Primary path — LLM, prompted with real example rows (no hardcoded rules)
```python
def make_rows(columns, example_rows, n, llm, scenario=None):
    """Generate n NEW coherent rows. Relationships are LEARNED from example_rows,
    never hardcoded. Works for ANY schema."""
    prompt = (
        f"You are generating synthetic test data.\n"
        f"COLUMNS (use exactly these, same names/order): {columns}\n"
        f"REAL EXAMPLE ROWS (infer the data types, formats, and the relationships "
        f"BETWEEN columns from these — do not assume any domain):\n{example_rows}\n"
        + (f"Generate rows for the '{scenario}' scenario "
           f"(valid=internally consistent & realistic; boundary=limit values; "
           f"negative=intentionally invalid in ONE or more fields; edge=unusual but plausible).\n"
           if scenario else "")
        + f"Rules:\n"
        f"- Keep each row INTERNALLY CONSISTENT according to the relationships you inferred "
        f"from the examples (whatever they are for this dataset).\n"
        f"- Produce NEW values; do not just copy the examples verbatim.\n"
        f"- Any column that looks like a unique id must get a NEW unique value.\n"
        f"- Return ONLY a JSON array of {n} objects with exactly the given columns."
    )
    rows = json.loads(llm(prompt))
    return [{c: r.get(c, "") for c in columns} for r in rows]
```
Key: the **examples carry the domain.** The LLM infers "country relates to currency" or
"free plan implies zero amount" *from the data*, so the same code works on loans, sensors,
anything. Nothing about subscriptions is in the agent.

### 1b. Fallback path — LLM unavailable (offline/tests), still no hardcoding
When there is no LLM, do not invent relationships. Instead **preserve coherence by sampling whole
real rows and perturbing only what the scenario requires**, learning everything from the data:

- **valid:** copy a real row, then change only "free-looking" fields (see 2a) to other values
  drawn from that same column's observed set. Because you start from a real (coherent) row and
  only swap independent-looking values, cross-column relationships survive.
- **boundary:** start from a real row; for numeric-looking columns substitute observed min/max
  (or 0 / very large); leave the rest of the row intact.
- **negative:** start from a real row; corrupt exactly ONE field (empty it, or insert a clearly
  invalid token) — keep the others coherent so the row is realistically "one thing wrong."
- **edge:** start from a real row; apply one unusual-but-valid observed value.

This "clone-a-real-row-then-perturb-minimally" strategy keeps rows coherent **without knowing what
the columns mean** — the coherence comes from the real row you started from, not from rules.

---

## 2. Data-driven inference helpers (all learn from the upload — zero domain knowledge)

These utilities let both paths behave well on any schema. None references a specific column name.

### 2a. Infer per-column "type" from observed values
For each column, scan the original rows and classify by content, not name:
```
- numeric        : all non-empty values parse as int/float
- datetime       : values parse as ISO/date
- categorical    : small number of distinct values (e.g. <= 15 uniques)  -> treat as an enum
- id-like        : (near-)unique per row AND matches a stable pattern (prefix + number, uuid...)
- freetext/other : everything else
```
Use this to decide how to generate/perturb a column — e.g. id-like -> mint a new unique id;
categorical -> draw from the observed set; numeric -> min/max for boundary.

### 2b. Mint unique values for id-like columns (fixes Defect 5)
If a column is id-like with pattern `PREFIX-<number>` (detected by regex on the observed values),
generate new rows continuing the sequence (`SUB-051`, `SUB-052`, ...). For uuid-like, generate
fresh uuids. **The prefix/format is read from the data**, not hardcoded. Never reuse an existing
id for a new row.

### 2c. Learn coherence groups from co-occurrence (optional, for the fallback path)
Without an LLM you can still detect that two categorical columns are correlated: if value A in
column X almost always co-occurs with value B in column Y across the real rows, keep that pairing
when generating. This reconstructs "country<->currency"-type links **statistically**, for whatever
columns happen to be correlated in *this* dataset — again, no names hardcoded.

---

## 3. Scenario mix — include valid; tag honestly (fixes Defects 4 & 6)

- **Always include `valid` rows** in the new data. Suggested default split when a
  scenario/category column exists: valid 40%, boundary 20%, negative 20%, edge 20% (shift toward
  gap types when `coverage_gaps` say so, but never drop valid to zero).
- **Tag = content.** A row generated for `negative` must actually be invalid in some field; a
  `valid` row must be coherent. Generate per scenario (section 1) so the label matches the data.
- Only write `scenario_tag` / `data_category` **if those columns exist in the upload** (a loan or
  sensor file may not have them). Schema-agnostic rule still wins.

---

## 4. Discount-code-type fields (fixes Defect 3) — generically

`discount_code` became `1,2,3,5` because it was treated as a fill-from-nothing column. The general
rule (no special-casing this field):
- If a column is **mostly empty** in the originals (optional field), new rows should **also be
  mostly empty** for it, occasionally drawing a real observed value (e.g. `ANNUAL20`, `CORP10`)
  from that column's value set.
- If a column is **freetext/code-like** (2a), generate values that match the **observed shape**
  (e.g. uppercase letters + digits, typical length), not a bare counter.
- Never emit a bare incrementing integer unless the column's real values are bare integers.

---

## 5. Exact change list

**`synthesise.py`** (or wherever rows are assembled)
- [ ] Remove index-zip assembly for NEW rows. Generate whole rows via `make_rows` (section 1a),
      LLM-first, with the clone-and-perturb fallback (1b).
- [ ] Pass real `example_rows` (a sample of the originals) into generation so relationships are
      inferred from data.
- [ ] Mint unique ids for id-like columns (2b); never reuse original ids.
- [ ] Ensure `valid` is in the scenario mix (section 3).
- [ ] Tag scenario columns only if present; make tag match content.
- [ ] Keep: originals preserved verbatim + output strictly larger than input (already working).

**`generate.py`**
- [ ] Replace any remaining hardcoded value tables with the data-driven type inference (2a) +
      observed-value sampling. No domain/column names in code.

**Universality guard (add to tests)**
- [ ] Run the agent on a **second, totally different schema** (e.g. a 5-column loans CSV with a
      different coherence rule) and assert it still expands, stays coherent, and never emits
      subscription-specific artifacts. This is the real proof the agent is schema-agnostic.

---

## 6. Acceptance criteria (re-test on subscription AND a second schema)

| Check | Pass condition |
|---|---|
| Coherence | new rows respect relationships inferred from the data (e.g. on subscription: country/currency match, free=>0 amount) — **with no hardcoded rules** |
| Universality | same agent run on a different-schema CSV produces coherent rows with zero subscription artifacts |
| Unique ids | id-like columns are unique across the whole output; new ids continue the observed pattern |
| Valid present | new rows include valid + boundary + negative + edge (when a category column exists) |
| Tag = content | every new row's scenario tag matches its actual values |
| Optional fields | mostly-empty columns stay mostly empty; code-like columns match observed shape (no bare 1,2,3) |
| Still additive & larger | all originals verbatim; output > input |

---

## 7. One-paragraph brief for Claude Code

> The structural fixes worked (expands 3x, originals preserved, schema kept, no `sample_value_*`).
> The remaining problem: the 100 new rows are incoherent because they're index-zipped permutations
> of the original column values — 83% have mismatched country/currency, 21 free plans cost money,
> ids duplicate, discount codes are 1/2/3/5, and there are no valid rows. Fix by generating each
> NEW row as a coherent whole, but **strictly schema-agnostically** — the subscription file is just
> one example; the next upload could be any domain with any columns and any relationships, so
> **never hardcode column names, value lists, or coherence rules.** Primary path: prompt the LLM
> with the exact columns + a sample of real rows and have it INFER the data types and inter-column
> relationships from those examples, generating fresh coherent rows per scenario. Offline fallback:
> clone a real row and perturb only what the scenario needs (so coherence survives without knowing
> the domain). Add data-driven helpers that infer per-column type from observed values, mint unique
> ids for id-like columns (continuing the observed pattern, never reusing), keep mostly-empty
> columns mostly empty, and match observed value shapes. Always include valid rows and make each
> row's scenario tag match its actual content. Prove universality with a test on a second, totally
> different schema. Keep the working guarantees: originals verbatim, output strictly larger.
