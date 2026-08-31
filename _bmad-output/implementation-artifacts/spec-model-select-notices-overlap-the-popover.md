---
title: 'Model select notices no longer cover the open catalog'
type: 'bugfix'
created: '2026-08-31'
status: 'done'
route: 'one-shot'
---

# Model select notices no longer cover the open catalog

## Intent

**Problem:** Opening the ask box's model select drew two absolutely positioned
layers against the same corner of the trigger — the catalog panel and the
notices box — so the source notice ("Inherited from the file default in
config.yaml…") landed on top of the catalog the reader had just opened.

**Approach:** In the compact ask box, lay the catalog and the notices out as
siblings of one positioned column under the trigger, catalog first. Overlap
becomes structurally impossible rather than a matter of offsets, the notices
box stays mounted whatever the popover is doing, and the notice markup itself
is unchanged.

## Suggested Review Order

- The notices as one always-mounted box; a `role="alert"` refusal is announced once, not per toggle.
  [`ModelSelect.tsx:167`](../../web/src/features/settings/ModelSelect.tsx#L167)

- The catalog panel positions itself only in the full view — in the ask box the column places it.
  [`ModelSelect.tsx:219`](../../web/src/features/settings/ModelSelect.tsx#L219)

- The column that carries both, and the full view's unchanged in-flow placement.
  [`ModelSelect.tsx:310`](../../web/src/features/settings/ModelSelect.tsx#L310)

- The structural invariant jsdom can actually see: siblings, in order, panel not positioned.
  [`ModelSelect.test.tsx:496`](../../web/src/features/settings/ModelSelect.test.tsx#L496)

- The source notice appears only while the popover is open, and closing returns focus.
  [`ModelSelect.test.tsx:527`](../../web/src/features/settings/ModelSelect.test.tsx#L527)

- The full view keeps its notices in the flow, on the same node, across a toggle.
  [`ModelSelect.test.tsx:540`](../../web/src/features/settings/ModelSelect.test.tsx#L540)
