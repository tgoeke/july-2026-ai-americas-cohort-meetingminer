# MeetingMiner

Agent operating rules for this repository live in **[AGENTS.md](AGENTS.md)** —
one file, read by every agent regardless of which tool is driving. Read it
before touching the tree.

The short version:

- **Commit and push without asking**, and commit early — uncommitted work is the
  only work another agent can destroy.
- **Never reset, stash, or clean a tree you do not exclusively own**, and never
  `git add -A`. Stage only the paths you changed.
- **Work in a worktree**: `make worktree STORY=<slug>`.
- **Each worktree has its own Docker stack** (`meetingminer-<slug>`, ports in
  its generated `.env.worktree`), so suites, rebuilds and workers in different
  worktrees never contend; two suites in one checkout queue on the projection
  lock. The api/web ports are still fixed. `make evals-run` remains one at a
  time.

The technical contract is [docs/architecture.md](docs/architecture.md); what has
been built and what it deliberately does not do is
[docs/project-record.md](docs/project-record.md); what is known-but-undone is
[docs/backlog.md](docs/backlog.md).
