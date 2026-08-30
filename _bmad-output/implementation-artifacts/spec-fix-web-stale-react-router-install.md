---
title: 'Fix stale web install missing react-router'
type: 'bugfix'
created: '2026-08-21'
status: 'done'
route: 'one-shot'
---

# Fix stale web install missing react-router

## Intent

**Problem:** The Vite dev server failed with `Failed to resolve import "react-router" from "src/App.tsx"`. The dependency was already declared in `web/package.json` (`react-router@^7.18.2`) and present in `pnpm-lock.yaml`, but this checkout's `web/node_modules` predated the commit that added it.

**Approach:** Environment-only fix: run `pnpm install` in `web/` to sync `node_modules` with the committed lockfile. No repository files changed. Verified with `pnpm exec tsc -b --noEmit` (clean) and `pnpm exec vite build` (built successfully).

## Suggested Review Order

Nothing to review in the tree — this run changed no tracked files. For confirmation only:

1. [web/package.json](../../web/package.json) — `react-router` was already declared; the fix installed what the lockfile already pinned.
