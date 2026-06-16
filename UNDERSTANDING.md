# Understanding the Test Data Mining Agent — A Ground-Up Guide

> This guide assumes you know basic Python and nothing else. It explains every concept,
> every piece of technology, and every bit of jargon in the project, then shows how they
> fit together. Read it top to bottom once; after that, use it as a reference.

---

## 1. The project in one paragraph

Every time your company's code is tested by an automated pipeline, it produces a pile of
result files — which tests passed, which failed, how long they took, and the error messages
for failures. Nobody has time to read all of that across hundreds of runs. **The Test Data
Mining Agent is a program that reads those result files automatically and tells a QA lead the
useful stuff:** which tests are unreliable ("flaky"), what's not being tested ("coverage
gaps"), which failures keep happening for the same underlying reason, and how the test suite's
health is trending. It only *reads and reports* — it never changes any tests or pipelines.

That's the whole thing. Everything below is detail about *how* it does that.

---

## 2. The problem, with a story

Imagine a test called `checkout_payment_test`. On Monday it passes. Tuesday it fails. Wednesday
it passes again — and nobody changed any code in between. That's a **flaky test**: it gives
different answers for the same code, usually because of timing, network hiccups, or shared
resources. Flaky tests are poison: developers start ignoring failures ("oh, that test is just
flaky"), and then a *real* bug slips through because everyone assumed it was noise.

Now multiply that by thousands of tests and hundreds of CI runs. The signal (real problems) is
buried in noise (flaky failures, repeated known issues). A human can't mine that by hand. So we
build an agent to do it — consistently, every run, and at scale.

The agent answers five questions (these are the project's five **goals**, labelled G1–G5):

| Goal | Question it answers |
|------|---------------------|
| G1 — Flaky detection | "Which tests pass *and* fail without a code change?" |
| G2 — Coverage gaps | "Which parts of the code aren't being tested?" |
| G3 — Failure clustering | "Which failures are really the same root problem?" |
| G4 — Suite health | "Is our test suite getting better or worse over time?" |
| G5 — Prioritised report | "Given all of the above, what should I fix first?" |

---

## 3. Glossary — the jargon, in plain words

Read this once so the rest makes sense. Don't memorise it; just get the gist.

**Agent.** A program that pursues a goal through several steps on its own, often using an AI
model to make some of the decisions. Unlike a plain script that does one fixed thing, an agent
moves through a *workflow* and can branch based on what it finds. Ours is a fairly structured,
predictable agent (by design — see "autonomy" below).

**LLM (Large Language Model).** The AI behind tools like Claude. You give it text, it gives you
text back. In this project the LLM is used for *language* tasks only: cleaning up messy error
messages, naming groups of failures, and writing the final human-readable recommendations. It
is deliberately **not** trusted with anything that must be exact (like counting how flaky a
test is) — that's done with plain, predictable Python.

**LangGraph.** The framework we use to build the agent as a *graph* of steps. (Explained
properly in §5.) Think "flowchart you can actually run."

**LangChain.** A broader toolkit for building LLM applications. LangGraph is built on top of it.
We use a small piece of it (`langchain-core`) for the basic LLM plumbing.

**Node.** One step in the workflow — a single Python function. E.g. the `ingest` node reads
files; the `flaky_detect` node scores flakiness. (More in §5.)

**State.** A shared "clipboard" of data that every node reads from and writes to as the workflow
runs. It starts mostly empty and fills up as each node does its job. (More in §5.)

**Edge.** A connection between two nodes that says "after this step, go to that step." A
*conditional* edge picks the next step based on the data.

**Pipeline.** The whole chain of nodes from start (read files) to finish (save report).

**Deterministic.** Always gives the same output for the same input. Pure maths/counting. The
opposite of an LLM, which can phrase things differently each time. Our detectors are
deterministic on purpose — so results are reproducible and trustworthy.

**Flaky test.** A test that passes sometimes and fails other times *without the code changing*.
The headline thing we detect.

**Coverage / coverage gap.** "Coverage" = how much of your code is actually exercised by tests.
A "gap" is code with little or no test coverage — a blind spot where bugs can hide.

**Failure signature.** A cleaned-up version of an error message + stack trace, stripped of the
bits that change every time (line numbers, timestamps, memory addresses), so that two failures
caused by the same thing look identical and can be grouped.

**Clustering.** Automatically grouping similar things together without being told the groups in
advance. We cluster failures by signature to find "this same failure happened 47 times."

**Embedding.** A way to turn a piece of text into a list of numbers (a "vector") that captures
its *meaning*, so a computer can measure how similar two texts are. (Explained in §6.3.)

**Vector / vector database.** A vector is just that list of numbers. A vector database stores
lots of them and can quickly find "which stored vectors are closest to this one" — i.e. which
texts mean roughly the same thing. We use this for clustering failures.

**Cosine similarity.** The maths trick for measuring how "close in meaning" two embedding
vectors are. 1.0 = basically identical, 0 = unrelated. (More in §6.3.)

**HITL (Human-in-the-loop).** A point where the agent pauses and waits for a person to review
or approve before continuing. Our agent pauses to let a QA lead filter the findings before they
get saved.

**Autonomy level (L1 / L2 / L3).** How much the agent does on its own. L1 = one shot, no pause.
L2 = pauses for human review (our default). L3 = fully automatic, no pause. (More in §9.)

**ADLC (Agent Development LifeCycle).** The six-phase method we follow to build the agent:
Problem Definition → Design → Development → Testing → Deployment → Monitoring. It's just a
disciplined recipe so we build the right thing and can prove it works.

**Golden set.** A small batch of data where we *already know the right answers* (e.g. "these 6
tests are truly flaky"). We run the agent on it and check whether it gets those answers right.
It's the answer key for grading the agent.

**Precision and recall.** Two scores for how good the agent's detection is.
- *Precision* = of the tests it *called* flaky, how many really were? (Did it cry wolf?)
- *Recall* = of the tests that really *are* flaky, how many did it catch? (Did it miss any?)
Both matter: high precision but low recall means it's cautious but misses things; high recall
but low precision means it catches everything but with lots of false alarms.

---

## 4. The big picture — how the pieces relate

Here's the whole system at a glance. Don't worry about the detail yet; just see the shape.

```
   CI/CD test result files                 (the raw input: XML + JSON)
            │
            ▼
   ┌──────────────────┐
   │  The Agent        │  a LangGraph pipeline of small Python steps (nodes)
   │  (Python program) │  ── uses an LLM only for language tasks
   └──────────────────┘
            │  along the way it uses two databases:
            │
            ├──►  ChromaDB  (vector DB)  → to group similar failures
            │
            └──►  MongoDB   (document DB) → to save the final report
            │
            ▼
   A prioritised quality report  →  shown to a QA lead (who reviews it midway)
```

Three things to take away:
1. The agent is **a Python program** organised as a pipeline of steps.
2. It uses **an LLM** for the "wordy" parts and **plain Python** for the "counting" parts.
3. It uses **two databases** for two different jobs — and deliberately **avoids a third kind**
   (a graph database / Neo4j) because we don't need it (explained in §6.4).

---

## 5. How LangGraph works (the heart of the project)

This is the most important concept, so we'll go slowly.

### 5.1 Why not just one big function?

You *could* write the whole agent as one giant Python function. But it would be hard to test,
hard to change, and impossible to pause halfway for human review. Instead we break the work into
small named steps and describe how they connect. That description is the **graph**, and
LangGraph runs it for us.

### 5.2 The three ingredients

**State** — the shared clipboard. In our code it's defined in `state.py` as `AgentState`. It
holds things like the list of test results, the flaky findings, the failure clusters, and the
final report. Every node receives the current state and returns the pieces it wants to add or
update. Think of it as a form that gets filled in section by section as it passes down a line of
clerks.

**Nodes** — the steps. Each node is a plain Python function shaped like this:

```python
def some_node(state):
    # look at what's in the state so far
    data = state["raw_results"]
    # do one job
    result = do_something(data)
    # return ONLY the part of the state you updated
    return {"flaky_findings": result}
```

That's the whole pattern. Every node in this project follows it.

**Edges** — the wiring. Edges say "after node A, run node B." Most edges are fixed. One edge in
our graph is *conditional*: after the analysis, *if* we're in supervised mode (L2) go to the
human-review step; otherwise skip straight to writing the report.

### 5.3 Our actual pipeline

```
ingest → validate → ┌ flaky_detect ┐
                    ├ coverage_gap ├ (these three run in parallel)
                    └ failure_clustering ┘
                          │
                    suite_health
                          │
                 (review — only if L2)        ← human-in-the-loop pause
                          │
                      synthesis               ← the LLM writes the report
                          │
                       persist                ← save report to MongoDB
```

What each node does:

| Node | Plain-English job | Brain type |
|------|-------------------|-----------|
| `ingest` | Open the result files and turn them all into one tidy list | plain Python |
| `validate` | Sanity-check the data; flag anything corrupt or too thin | plain Python |
| `flaky_detect` | Score how flaky each test is | plain Python (deterministic) |
| `coverage_gap` | Find under-tested modules | plain Python |
| `failure_clustering` | Group similar failures together | vector DB + a little LLM |
| `suite_health` | Compute overall pass rate, speed, flake rate | plain Python |
| `review` | Pause for the QA lead to confirm/filter findings | human |
| `synthesis` | Rank everything and write recommendations | LLM |
| `persist` | Save the final report | plain Python |

"Run in parallel" just means those three analyses don't depend on each other, so LangGraph can
do them together rather than waiting in line — faster, and cleanly separated.

### 5.4 Checkpointing (why the pause is possible)

LangGraph can *save the state partway through* and resume later. That saved snapshot is a
**checkpoint**, and the component that does it is a **checkpointer**. This is what makes the
human-review pause possible: the agent freezes at the `review` node, a person looks at the
findings, and then the agent thaws and carries on. For now we use a simple in-memory
checkpointer called `MemorySaver`.

---

## 6. The tech stack — every tool and why it's here

### 6.1 The quick map

| Tool | Category | What it does for us |
|------|----------|---------------------|
| Python 3.11+ | Language | Everything is written in Python |
| LangGraph | Agent framework | Runs the pipeline of nodes (§5) |
| LangChain core | LLM plumbing | Standard way to talk to the LLM |
| An LLM (Claude) | AI model | Cleans error text, labels clusters, writes the report |
| ChromaDB | Vector database | Groups similar failures by meaning (§6.3) |
| MongoDB | Document database | Stores the final reports (§6.4) |
| FastAPI | Web framework | Lets other systems trigger the agent over the web |
| junitparser / lxml | XML parsing | Read JUnit/TestNG result files robustly |
| pytest | Testing tool | Run our automated tests |

### 6.2 Why an LLM *and* plain Python (the golden rule of this project)

The single most important design choice: **deterministic detectors first, LLM last.**

- Counting how often a test failed, computing a flakiness score, calculating a pass rate — these
  must be *exact and reproducible*. Plain Python does them. An LLM must never be asked to do
  these, because it could give slightly different answers and you couldn't trust the numbers.
- Reading a messy error message and writing "these failures all look like database timeouts" —
  that's a *language* task where an LLM shines. So the LLM only does the wordy parts.

If you remember one rule from this whole document, make it that one.

### 6.3 Vector databases, embeddings, and cosine similarity (for clustering)

This is the trickiest concept, so here's an analogy.

Imagine every error message is a point on a giant map. Messages about the same problem ("timeout
waiting for element") land near each other; unrelated ones ("null pointer in payment") land far
away. **Embeddings** are what place each message on that map: an embedding model reads the text
and outputs coordinates (a long list of numbers — a *vector*). Texts with similar *meaning* get
similar coordinates, even if the exact words differ.

**Cosine similarity** is the ruler we use to measure the distance between two points on that map.
It returns a number from 0 (totally unrelated) to 1 (essentially the same). To group failures,
we put all their embeddings on the map and gather together the ones that sit close — that's
**clustering**, and the result is "this same failure happened 47 times across 9 tests."

A **vector database** (ChromaDB) is simply a store built for exactly this: keep millions of these
coordinate-vectors and instantly answer "what's near this point?" That's why clustering uses a
vector DB and not a normal table-based database — ordinary databases are great at exact matches
("find the row where id = 5") but bad at "find things that *mean* something similar."

Note a subtle two-step in our `failure_clustering` node: the **vector DB forms the groups**
(pure maths on the embeddings), and then **the LLM just labels each group** with a human-readable
name. Two different tools, two different jobs.

### 6.4 The two databases, and the one we refuse to use

**MongoDB — a document database.** Think of it as storing JSON documents (like flexible folders
of data) rather than rigid spreadsheet tables. We use it to save the final reports and, later, to
store simple links between tests and the requirements they cover. It's already used across the
wider platform, so we're not adding anything new.

**ChromaDB — a vector database.** Covered in §6.3. Used only for failure clustering. Also already
in the platform.

**Neo4j — a graph database — which we deliberately DO NOT use.** A graph database is specialised
for data shaped like a web of relationships with deep chains ("A knows B who manages C who owns
D…", traversed many hops deep). It's powerful but heavy. Our project was checked for whether it
needs one, and the answer is no:
- Grouping similar failures is a *similarity* problem → that's a vector DB's job, not a graph's.
- Linking a test to its requirement is a *shallow* lookup (one or two hops) → a simple MongoDB
  query handles it.

Adding Neo4j would mean running and maintaining an entire extra database for no real benefit —
classic over-engineering. So the project's rule is firm: **no graph database, no Neo4j, anywhere.**
You'll see this called out repeatedly in the spec and the code; now you know why.

### 6.5 FastAPI (how the agent gets triggered)

FastAPI is a Python framework for building web services. In production, the agent lives inside a
FastAPI service so other systems can start it — a person clicking "run" in a dashboard, a nightly
schedule, or the CI pipeline pinging it after a run. You don't need this to develop locally
(you can run the agent directly from the command line), but it's how it'll be reached once
deployed.

---

## 7. A full walkthrough — following one run end to end

Let's trace a single run so the abstractions become concrete.

1. **Trigger.** A QA lead clicks "analyse project X." The agent starts with a fresh **state**
   that knows where the result files are and which autonomy level to use (say L2).

2. **`ingest`.** It walks the folders, opens every JUnit XML and Playwright JSON file, and turns
   them all into one uniform list of `TestResult` records (test name, pass/fail, duration, which
   run, error message). Different file formats in, one tidy list out.

3. **`validate`.** It checks the list isn't empty or corrupt and flags tests that don't have
   enough run history to judge. If something's wrong it notes it but keeps going — the agent is
   built to *degrade gracefully*, never crash.

4. **Parallel analysis** (three nodes at once):
   - `flaky_detect` groups each test's outcomes across runs and computes a flakiness score. A test
     that both passed and failed (with the failures happening at least twice, to rule out a
     one-off) gets flagged flaky. A test that fails *every* time is a real regression, **not**
     flaky — the detector keeps those separate on purpose.
   - `coverage_gap` looks for under-tested modules (full version arrives in Phase 2).
   - `failure_clustering` embeds the failure messages, groups the similar ones via ChromaDB, and
     has the LLM name each group.

5. **`suite_health`.** Computes the headline numbers: overall pass rate, average duration, flake
   rate, and how many runs were in the window.

6. **`review` (because we're in L2).** The agent **pauses**. The QA lead sees the draft findings
   and can deselect false alarms or confirm the list. Then the agent resumes. (In L1 or L3 this
   step is skipped entirely.)

7. **`synthesis`.** The LLM takes the confirmed findings and writes the deliverable: a ranked
   list of issues with plain-English recommendations ("Quarantine these 3 flaky tests; investigate
   the database-timeout cluster affecting checkout").

8. **`persist`.** The report is saved to MongoDB so it can be displayed and kept for history.

That's one complete mining run.

---

## 8. How the concepts map to the actual files

So when you open the repo, you know what you're looking at:

| File | What it is |
|------|-----------|
| `CLAUDE.md` | The working contract / summary (Claude Code reads it automatically) |
| `docs/test-data-mining.md` | The full approved design spec — the source of truth |
| `src/test_data_mining/state.py` | Defines the shared **state** (the clipboard) — §5.2 |
| `src/test_data_mining/graph.py` | Wires the nodes together into the **pipeline** — §5.3 |
| `src/test_data_mining/nodes/ingest.py` | The `ingest` node — file readers (works today) |
| `src/test_data_mining/nodes/flaky_detect.py` | The `flaky_detect` node — scoring (works today) |
| `src/test_data_mining/nodes/stubs.py` | The not-yet-built nodes, with TODO notes |
| `scripts/generate_fixtures.py` | Makes fake-but-realistic test data to develop against |
| `scripts/score_golden.py` | Grades the detector's precision/recall against known answers |
| `tests/test_flaky_detect.py` | Automated tests for the detector |
| `data/fixtures/` | The generated test data |
| `data/golden/` | The answer key (which tests are truly flaky) |
| `ROADMAP.md` | The step-by-step build checklist |
| `DATA.md` | Where the data comes from and why we generate our own |

A good first exercise: open `state.py` and read the field names — that single file tells you
everything the agent tracks. Then open `flaky_detect.py` and see how a real node reads the state
and returns a result. Those two files will make §5 click.

---

## 9. Autonomy levels and human-in-the-loop

The same agent can run at three levels of independence, chosen per project:

| Level | Behaviour | When you'd use it |
|-------|-----------|-------------------|
| **L1 — Assistive** | One shot, no pause. Read → analyse → report. | Quick, low-stakes checks |
| **L2 — Supervised** (default) | Pauses so a human reviews/filters findings before saving. | Normal use — keeps a human in control |
| **L3 — Goal-driven** | Fully automatic, saves without a pause. | Trusted, mature pipelines |

The only structural difference between them is whether the `review` node runs. That's handled by
the one conditional edge in `graph.py`. We default to L2 because a human glance prevents bad
findings from being trusted automatically — important while the agent is still earning trust.

---

## 10. How we prove it works (and why the data is "fake")

You can't grade detection without knowing the right answers. Real CI data doesn't come with a
label saying "this test is definitely flaky." So we **generate our own test data** where we
control — and therefore know — which tests are flaky, which are real regressions, and which are
stable. That known-answer set is the **golden set**.

We then run the agent on it and compute **precision** and **recall** (defined in §3). The project
targets are precision ≥ 0.85 and recall ≥ 0.75 for flaky detection. The starter code already
meets them on the generated data. Later, for the real pilot, a QA lead will hand-label a small
set of real failures to grade the agent on genuine data too.

(There are public datasets — IDoFT, FlakeFlagger, a Kaggle CI/CD dataset — but none is in the
exact raw format the agent reads *and* pre-labelled, so they're useful for added realism later,
not for getting started. `DATA.md` has the full reasoning.)

---

## 11. The five-second summary to keep in your head

- It's a **Python pipeline** (built with **LangGraph**) that **reads test results and reports
  insights** — read-only, never changes anything.
- It uses **plain Python for exact things** (scores, counts) and an **LLM only for wordy things**
  (labels, recommendations).
- It uses **ChromaDB** (a vector database) to **group similar failures by meaning**, and
  **MongoDB** to **save reports**. It pointedly **does not use a graph database**.
- It can **pause for a human** (HITL) before saving, depending on the **autonomy level** (default
  L2).
- We prove it works by grading it against a **golden set** using **precision and recall**.

If those five bullets make sense, you understand the project. Everything else is detail you can
look up here when you need it.

---

## 12. Where to go next

1. Read this doc once more, skimming the parts that already feel clear.
2. Open `state.py`, then `flaky_detect.py`, with §5 and §8 beside you.
3. Run the three commands in the README (`generate_fixtures.py`, `pytest`, `score_golden.py`) and
   watch the numbers — seeing it work makes it real.
4. Open `ROADMAP.md` and look at the next unchecked milestone. That's what gets built next.

Whenever a word stops you, come back to the glossary in §3.
