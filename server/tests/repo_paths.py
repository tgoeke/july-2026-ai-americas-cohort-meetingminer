"""The repository root, for tests that read files by repo-relative path.

This used to be a name in ``conftest.py``. Importing it from there made every
importer depend on the plugin module for one constant (story 11.1). Tests may
anchor on their own location; only ``meetingminer.config`` is barred from
``__file__``-derived repo paths (story 1.10, finding 17).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
