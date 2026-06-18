# UNDERSTANDING.md — The agent in plain English

> No jargon. For anyone (manager, new joiner, or an AI getting oriented) who wants to *get it* in
> five minutes. The precise version is [`CONTEXT.md`](CONTEXT.md).

---

## The one-sentence version

You give it a spreadsheet of test data; it hands back the same spreadsheet **plus a bunch of new,
realistic rows** to test with — and lets you steer what gets made.

---

## The problem it solves

QA engineers need lots of test data: normal cases, weird edge cases, things that *should* fail.
Making that by hand is slow and you always miss combinations. This agent **fills the gaps
automatically** while keeping the data realistic.

---

## How it works, as a story

1. **You upload two things.**
   - *Test cases* — a sheet (or user stories) that says **what columns/fields** you need.
   - *Test results* (optional) — your JUnit/Playwright files, which tell the agent **what's already
     been tested** and give it **real example values** to copy the style of.

2. **It looks around for data it can reuse.**
   - **Fetched** = pulls matching data it already has stored (in MongoDB).
   - **Gathered** = finds *similar* past datasets by meaning (using ChromaDB + a small AI embedding
     model that runs on your machine, no internet needed).

3. **It spots what's missing.** It checks every field against four kinds of test — *valid, boundary,
   negative, edge* — and sees which combinations your results never covered. Those are the gaps.

4. **It suggests values, you choose.** For each field it offers a few options ("use these valid
   values" / "use these gap-filling values"). You pick. This is the **human-in-the-loop** step — it
   always asks, never guesses silently.

5. **It builds new rows — whole rows, not random columns.** This is the important bit: it makes each
   new row *make sense together*. It won't pair a "free plan" with a "$35,000 charge", or a country
   with the wrong currency. It learns those relationships **from your data**, so it works for *any*
   kind of data — orders, loans, sensor readings, anything.

6. **You get a clean spreadsheet.** Original rows first (untouched), then the new rows. Always more
   rows than you started with. The download is **pure data** — no extra columns.

7. **On screen, every row is colour-coded** by where it came from: your **input**, freshly
   **generated**, **fetched**, or **gathered**. (That colour is just on screen — it's never in the
   downloaded file.)

8. **Want more? Iterate.** Tick the rows you like and click **"Generate more from selected"** — it
   makes a fresh batch based on your picks. Repeat until happy.

9. **Optionally save it back** so next time there's even more to reuse.

---

## The rules it always follows

- **Never throws away your data.** Your original rows come back exactly as they were.
- **Always gives you more, never fewer rows.**
- **Same columns you uploaded** — it never adds or renames columns.
- **No made-up nonsense** — values respect the field's rules (an email has an "@", a currency is a
  real 3-letter code), and there are never placeholder values like `sample_value_1`.
- **Works offline** — no internet required; if the optional AI isn't available it falls back to a
  simpler-but-still-sensible method.
- **Only writes when you say so** — it reads freely but saves to the database only on an explicit
  "Save".

---

## Why it's trustworthy for any kind of data

It doesn't have "subscriptions" or "orders" baked into it. It *reads your spreadsheet and figures
out the patterns at runtime* — which column is an id, which is a price, which two columns always go
together. That's why the same agent works on a loans file or a temperature-sensor log without any
code changes (and there are tests that prove exactly that).

---

## Where to go next

- The big picture & rules → [`CONTEXT.md`](CONTEXT.md)
- The pieces and how they connect → [`ARCHITECTURE.md`](ARCHITECTURE.md) + [`architecture.svg`](architecture.svg)
- How data moves, with diagrams → [`DATA-FLOW.md`](DATA-FLOW.md)
- The web API → [`BACKEND.md`](BACKEND.md)
