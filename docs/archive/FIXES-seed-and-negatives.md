# FIXES-seed-and-negatives.md — Two targeted fixes

> **For Claude Code.** The core engine is verified working on real data (`test-data__5_.csv`):
> output 120 > input 50, originals preserved verbatim, generated block coherent (no free@nonzero,
> real discount codes, valid+boundary+negative+edge spread, negatives correctly invalid), clean
> CSV with no source column. **Do not touch the generation/coherence logic — it's correct.**
>
> Two small, targeted issues remain. Both are about **data quality of the fetched/gathered rows
> and a negative-row edge case** — not the generator. Keep all invariants in `CONTEXT.md §2`.

---

## Fix 1 — Fetched/gathered rows are sparse (the real weak spot)

### Evidence
The last 20 output rows (SUB-101–120 — the fetched + gathered block) are nearly empty:
```
SUB-101 -> customer_name=User_0001, email=user0001@example.com         (everything else blank)
SUB-108 -> User_0001, user0001@example.com, country=US, currency=USD   (still no plan/amount/status/dates)
```
Only `customer_name` + `email` (sometimes + country/currency) are populated; `plan_type`,
`billing_cycle`, `amount`, `discount_code`, `subscription_status`, `start_date` are all blank. The
values (`User_0001`, `user0001@example.com`) are also seed-placeholder-style, not realistic.

### Why it happens (root cause — NOT the generator)
This is a **seed-data quality problem**, not a synthesise bug. The MongoDB/ChromaDB seed only stores
a few fields per record. In `generate_fixtures.py`, `_write_mongo` builds documents whose `fields`
cover only a small `REUSED_FIELDS` subset, and the rows stored alongside are correspondingly thin.
So when `mongo_lookup` (fetched) and `vector_search` (gathered) return those records, the rows they
contribute are mostly blank — and `synthesise` faithfully includes them as-is.

### How to fix (in `scripts/generate_fixtures.py`)
- [ ] Seed MongoDB/ChromaDB with **full, realistic rows**, not a thin field subset. Store complete
      records (all columns of the source schema) so fetched/gathered rows are as rich as generated
      ones. Pull them straight from the real source CSV rows (e.g. a sample of
      `subscription_tests_v2.csv`'s valid rows) so every stored row has plan_type, amount, currency,
      status, dates, etc.
- [ ] Keep the existing `fields` (column pools) for matching, but **also store the full row dicts**
      (`rows`) with every column populated — `mongo_lookup`/`vector_search` already read row-aligned
      `rows`, so this just makes those rows complete.
- [ ] Replace placeholder-style values (`User_0001`, `user0001@example.com`) with the **real values
      from the source CSV** so reused rows look like genuine data. Do not synthesise new
      `User_NNNN` names in the seed.
- [ ] Deliberately leave SOME fields/scenarios out of the seed (so there's still a coverage gap to
      fill) — but a seeded row that IS returned should be **complete**, not a 2-field stub.

### Acceptance
- Fetched/gathered rows in the output have **all columns populated** (or as populated as a real
  stored record would be), not just name+email.
- No `User_0001`-style placeholder values in fetched/gathered rows; they carry real values.
- A coverage gap still exists (some scenarios remain for the generator to fill).

> Schema-agnostic note: the seeding must read whatever columns the source CSV has — do not hardcode
> the subscription columns. `--source <csv>` (already planned) drives which schema is seeded.

---

## Fix 2 — Negative rows with empty `subscription_id` (confirm intent)

### Evidence
Four rows tagged `negative` have a blank primary key:
```
[negative] subscription_id=''  name='Marco Rossi'  tag=negative_013
[negative] subscription_id=''  name='Bulk Seats'   tag=negative_022
[negative] subscription_id=''  name='Future Discount' tag=negative_037
[negative] subscription_id=''  name='Multi Discount'  tag=negative_046
```

### Why it happens
`synthesise`'s negative-scenario path empties a high-fill field to make the row "invalid in one
field." Sometimes the field it empties is the **primary-key / id-like column**. A missing-required-id
IS a legitimate negative test — but a blank primary key can break downstream tools that key on it,
and it collides with other blank-id rows (they're no longer unique).

### Decision needed (pick one — confirm with the team)
- **Option A (recommended):** the negative perturbation may empty/corrupt any high-fill field
  **except an id-like column**. Id-like columns always get a freshly minted unique id, even in
  negative rows; invalidity is expressed in some *other* field. This keeps primary keys unique and
  non-null while still producing valid negative cases.
- **Option B:** allow a blank/invalid id as a negative case, but make it a **non-empty invalid
  value** (e.g. `SUB-` with no number, or `INVALID-ID`) rather than empty string — so it's still
  unique-ish and downstream tools don't choke on null keys.
- **Option C:** keep as-is (empty id is an intended negative). Only choose this if the consuming
  system explicitly wants null-PK negatives.

### How to fix (in `synthesise` / the negative perturbation, using `inference.py`)
- [ ] Use the existing column profiling to detect **id-like columns** (already implemented in
      `inference.py` for unique-id minting).
- [ ] In the negative path, **exclude id-like columns from the "empty one field" choice** (Option A),
      OR substitute a non-empty invalid token (Option B). Never leave the primary key as `''`.
- [ ] Ensure every row (including negatives) still has a **unique** id (no duplicate blank ids).

### Acceptance
- No two output rows share a blank/duplicate `subscription_id` (or whichever column is the id).
- Negative rows are still genuinely invalid — just not via a null primary key (unless Option C is
  explicitly chosen).

---

## Summary for Claude Code

> The generator is verified correct — do not change coherence/additive/provenance logic. Make two
> data-quality fixes only. (1) In `generate_fixtures.py`, seed MongoDB/ChromaDB with **full
> realistic rows from the source CSV** (all columns populated, real values, no `User_0001`
> placeholders) so the fetched/gathered rows in the output aren't sparse 2-field stubs — while still
> leaving some scenarios unseeded so a coverage gap remains. (2) In the negative-scenario
> perturbation, **never empty the id-like/primary-key column** (detect it via `inference.py`); mint a
> unique id for every row and express negative invalidity in some other field (or use a non-empty
> invalid id token). Keep all `CONTEXT.md §2` invariants; stay schema-agnostic (read columns from the
> uploaded/source data, don't hardcode subscription fields).
