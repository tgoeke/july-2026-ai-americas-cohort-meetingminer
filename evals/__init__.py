"""MeetingMiner eval harness (Epic 5).

A package, not a loose directory, so ``evals/tests`` can import
``evals.harness`` without sys.path manipulation: pytest's prepend import mode
walks up while ``__init__.py`` exists and puts the repository root on the path.

Per AD-16 the harness is a client of the running system, never a housemate. It
mutates state only through the public API and asserts through API reads and
read-only store access. ``tests/test_harness_boundary.py`` is the mechanism
that enforces that instead of leaving it to convention.
"""
