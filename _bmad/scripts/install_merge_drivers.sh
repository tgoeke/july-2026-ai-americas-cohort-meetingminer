#!/usr/bin/env bash
# Register this repo's custom merge drivers. Run once per clone.
#
# Worktrees share the common .git/config, so one run covers every worktree
# created by `make worktree`. Safe to re-run.
#
# .gitattributes names `merge=sprint-status`; only this registration tells git
# what that means. Without it git silently falls back to the default merge and
# the conflicts come back — which is why this is a named script rather than a
# comment somebody is supposed to notice.
set -euo pipefail
# The driver path must be RELATIVE: worktrees share the common .git/config, so
# an absolute path baked in by one worktree dangles for every other worktree
# the moment that one is removed (this happened when 2-1b's worktree was
# deleted after merge). Git runs merge drivers from the top of the working
# tree, and every worktree carries its own copy of the script at this relative
# path, so each worktree resolves its own.
git config merge.sprint-status.name "sprint-status.yaml key-wise merge"
git config merge.sprint-status.driver "python3 _bmad/scripts/merge_sprint_status.py %O %A %B %P"
echo "registered: merge.sprint-status -> _bmad/scripts/merge_sprint_status.py (relative to each worktree root)"
echo "verify with: git config --get merge.sprint-status.driver"
