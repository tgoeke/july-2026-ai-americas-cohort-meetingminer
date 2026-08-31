# Owner ruling — Story 10.3 finding F2: one canonical window anchor

**Ruling, 2026-08-31: the mention anchor owns window membership at every level.**

## The contradiction being resolved

Story 10.3's frozen contract required three things that cannot all hold:

1. coarse levels aggregate over `topic_mention.anchor_ms`, never joining `moment`;
2. a fine row's `occurredAt` derives from `moment.start_ms`;
3. counts agree across levels.

The review demonstrated the failure concretely: a moment starting at 59 s whose
mention anchor is 61 s makes a `[60 s, 62 s]` window count the mention in the
coarse tiers and envelope totals while excluding the row from the fine tier —
`momentCount: 1` with no moments returned. `[58 s, 60 s]` produces the inverse.
Widening the bucket does not help; the disagreement reproduces at any ladder
boundary.

## What is decided

**`topic_mention.anchor_ms` is the single semantic anchor for window membership
and for every level transition, at all four levels.** A moment appears in a
window when the *mention* that put it there falls inside the window, not when
the moment's own start does.

**Why.** A thread is made of mentions. The mention is the thing being followed
across meetings; the moment is the evidence a reader opens once they arrive.
Membership should therefore be decided by the unit the feature is about. This
also preserves the constraint that coarse tiers never join `moment`, which the
review measured as a real access-path property rather than a stylistic
preference, and it keeps the fix inside the query layer instead of trading one
contradiction for a performance regression.

Choosing the moment's start instead would have forced coarse aggregation to
obtain a moment start without joining `moment`, which is the constraint the
story exists to honour.

## What the contract must now say

The frozen spec is amended by this ruling, and the amendment is part of the fix
rather than a follow-up:

- Window membership at every level is `anchor_ms ∈ [from, to]`. Envelope totals
  and every tier's rows are selected by that one predicate, so a count and the
  rows it describes can no longer disagree.
- `occurredAt` on a fine row continues to derive from `moment.start_ms`, because
  it names when the evidence begins and a reader seeks to it. **It is therefore
  explicitly permitted for a returned row's `occurredAt` to fall outside the
  requested window** — it is a property of the evidence, not the selector.
- That permission must be stated on the wire contract rather than left implied,
  since a client would otherwise reasonably assume `occurredAt` is bounded by
  the window it asked for. Story 10.6 renders these rows and must not assume
  containment.

**Do not resolve this by adjusting only the envelope count.** The review named
that as the wrong fix and it remains excluded: it would hide the disagreement
rather than remove it.

## Finding F3 — ordinal reuse after deletion

**Not fixed for this story; it stands as filed backlog.** F3 observes that the
record does not prevent an explicit insert from reusing a colour ordinal freed
by a deletion. Nothing in the running system deletes threads, the derivation
allocates through the sequence, and the consequence is a repeated colour rather
than a wrong answer. A tombstone table is out of proportion to that. Revisit if
thread deletion becomes a real operation.
