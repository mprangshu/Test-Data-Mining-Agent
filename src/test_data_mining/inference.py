"""
inference.py — Data-driven schema inference (IMPROVEMENT-2.md §2). ZERO domain knowledge.

Everything here is learned **from the uploaded values at runtime** — never from column names. The
same code works on subscriptions, loans, sensors, anything. It classifies each column by the shape
of its observed values, detects id patterns so new rows get fresh unique ids, measures how often a
column is filled (so mostly-empty columns stay mostly empty), and learns value co-occurrence so a
correlation like country↔currency survives generation without any hardcoded rule.

If you ever need to type a specific column name in here, stop — that's the bug we're removing.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?(?:Z|[+-]\d{2}:?\d{2})?$")
_ID_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)$")        # PREFIX-<number>, e.g. SUB-001, ORD-100002
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")        # code-like token (no spaces)

_CATEGORICAL_MAX = 15        # ≤ this many distinct values → treat as an enum


def _s(v) -> str:
    # Normalise any value to a stripped string.
    return str(v).strip()


def _nonempty(values) -> list[str]:
    # Return only the non-empty string values from the input sequence.
    # Caller: column profilers call this to ignore blanks when inferring types/stats.
    return [_s(v) for v in values if _s(v) != ""]


def is_number(v) -> bool:
    # Detect numeric strings including decimals, ignoring commas.
    return bool(_FLOAT_RE.match(_s(v).replace(",", "")))


def is_integer(v) -> bool:
    # Detect integer strings, ignoring commas.
    return bool(_INT_RE.match(_s(v).replace(",", "")))


def is_datetime(v) -> bool:
    # Detect ISO-like date/time strings.
    return bool(_DATE_RE.match(_s(v)))


def _looks_like_id(values: list[str]) -> bool:
    """Same non-empty prefix with a varying trailing number across (near) all values."""
    matches = [_ID_RE.match(v) for v in values]
    if not all(matches):
        return False
    prefixes = {m.group("prefix") for m in matches}
    return len(prefixes) == 1 and next(iter(prefixes)) != ""


def id_pattern(values) -> tuple[str, int, int] | None:
    """Return (prefix, zero-pad width, max number) if the column is PREFIX-<number>, else None."""
    matches = [_ID_RE.match(v) for v in _nonempty(values)]
    matches = [m for m in matches if m]
    if not matches:
        return None
    prefixes = {m.group("prefix") for m in matches}
    if len(prefixes) != 1:
        return None
    prefix = next(iter(prefixes))
    width = max(len(m.group("num")) for m in matches)
    max_num = max(int(m.group("num")) for m in matches)
    # Return the id prefix, padding width, and current max sequence number.
    return prefix, width, max_num


def infer_column_type(values) -> str:
    """Classify a column by content: numeric | datetime | id | categorical | freetext | empty.

    Input: sequence of raw values for the column.
    Output: one of the canonical type strings. Callers: `profile_column`.
    """
    vals = _nonempty(values)
    if not vals:
        return "empty"
    uniq = list(dict.fromkeys(vals))
    if all(is_number(v) for v in vals):
        return "numeric"
    if all(is_datetime(v) for v in vals):
        return "datetime"
    if len(uniq) >= max(2, int(0.9 * len(vals))) and _looks_like_id(vals):
        return "id"
    if len(uniq) <= _CATEGORICAL_MAX:
        return "categorical"
    return "freetext"


@dataclass
class ColProfile:
    name: str
    ctype: str                       # numeric | datetime | id | categorical | freetext | empty
    fill_rate: float                 # fraction of rows where this column is non-empty
    observed: list = field(default_factory=list)   # distinct non-empty values, order-preserved
    id_prefix: str = ""
    id_width: int = 1
    id_max: int = 0
    num_min: float = 0.0
    num_max: float = 0.0
    code_like: bool = False          # values look like uppercase/alnum codes (e.g. WELCOME10)

    @property
    def numeric_is_int(self) -> bool:
        return self.ctype == "numeric" and all(is_integer(v) for v in self.observed)


def profile_column(name: str, values) -> ColProfile:
    # Build a ColProfile from the raw column values and detect special types.
    # Returns a ColProfile dataclass containing type, fill rate, observed values,
    # and numeric/id summary stats. Callers: `profile_columns`, `IdMinter`.
    all_vals = list(values)
    ne = _nonempty(all_vals)
    fill = (len(ne) / len(all_vals)) if all_vals else 0.0
    ctype = infer_column_type(all_vals)
    observed = list(dict.fromkeys(ne))
    p = ColProfile(name=name, ctype=ctype, fill_rate=fill, observed=observed)
    if ctype == "id":
        ip = id_pattern(all_vals)
        if ip:
            p.id_prefix, p.id_width, p.id_max = ip
    if ctype == "numeric":
        nums = [float(_s(v).replace(",", "")) for v in ne if is_number(v)]
        if nums:
            p.num_min, p.num_max = min(nums), max(nums)
    if observed:
        p.code_like = all(_CODE_RE.match(v) and not v.isspace() for v in observed) \
            and any(not v.isdigit() for v in observed)
    return p


def profile_columns(rows: list[dict], columns: list[str]) -> dict[str, ColProfile]:
    """Profile every column from the observed rows (schema-agnostic)."""
    # Profile each requested column over the input row corpus.
    return {c: profile_column(c, [r.get(c, "") for r in rows]) for c in columns}


class IdMinter:
    """Mints fresh unique ids per id-like column, continuing the observed PREFIX-<number> sequence.
    Never reuses an existing value (fixes IMPROVEMENT-2 Defect 5)."""

    def __init__(self, profiles: dict[str, ColProfile]):
        # Initialise minting state for each detected id-like column.
        self._next: dict[str, int] = {}
        self._width: dict[str, int] = {}
        self._prefix: dict[str, str] = {}
        for name, p in profiles.items():
            if p.ctype == "id":
                self._next[name] = p.id_max + 1
                self._width[name] = max(p.id_width, 1)
                self._prefix[name] = p.id_prefix

    def is_id(self, col: str) -> bool:
        # Report whether the column is recognised as an id-like sequence.
        return col in self._next

    def mint(self, col: str) -> str:
        # Return the next unique id for the given id-like column.
        # Output example: prefix + zero-padded number, e.g. 'SUB-00123'.
        n = self._next[col]
        self._next[col] = n + 1
        return f"{self._prefix[col]}{n:0{self._width[col]}d}"


def cooccurrence(rows: list[dict], col_a: str, col_b: str) -> dict[str, str]:
    """For each value of col_a, the most common co-occurring value of col_b (statistical coherence,
    IMPROVEMENT-2 §2c). Used only by the offline fallback to preserve correlations like
    country↔currency — for *whatever* columns happen to correlate in THIS dataset."""
    pairs: dict[str, Counter] = defaultdict(Counter)
    # Count the most frequent value of col_b for each seen value of col_a.
    for r in rows:
        a, b = _s(r.get(col_a, "")), _s(r.get(col_b, ""))
        if a and b:
            pairs[a][b] += 1
    return {a: counter.most_common(1)[0][0] for a, counter in pairs.items() if counter}


def correlated_pairs(rows: list[dict], profiles: dict[str, ColProfile],
                     min_strength: float = 0.9) -> list[tuple[str, str]]:
    """Pairs of categorical columns where one strongly predicts the other (≥ min_strength).
    Direction (a→b) means: given a's value, b is almost always the same. Schema-agnostic."""
    # Returns list of (a,b) pairs where a predicts b. Callers: `synthesise` uses these to
    # carry correlated partners when perturbing/generated edge cases.
    cats = [c for c, p in profiles.items() if p.ctype == "categorical"]
    out: list[tuple[str, str]] = []
    # Identify categorical column pairs with strong predictive co-occurrence.
    for a in cats:
        for b in cats:
            if a == b:
                continue
            groups: dict[str, Counter] = defaultdict(Counter)
            total = 0
            for r in rows:
                av, bv = _s(r.get(a, "")), _s(r.get(b, ""))
                if av and bv:
                    groups[av][bv] += 1
                    total += 1
            if total == 0:
                continue
            agree = sum(counter.most_common(1)[0][1] for counter in groups.values())
            if agree / total >= min_strength and len(groups) > 1:
                out.append((a, b))
    return out
