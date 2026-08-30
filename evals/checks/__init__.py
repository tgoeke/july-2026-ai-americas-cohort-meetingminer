"""The store-backed tier-1 checks (eval-design §2.1-2.4).

Separate from ``evals/tests/`` on purpose, and the split is the whole design:

* ``evals/tests/`` is store-free and api-free. It runs under ``make test`` in
  the group ahead of ``infra-up``, alongside the puller and web suites, and it
  exercises every check algorithm over synthetic captures.
* ``evals/checks/`` — this package — is one eval *run*. It needs the api up,
  the stores up, and the scripted meetings ingested, so it has its own target
  (``make evals-run``). It reads the shared dev stores read-only; the one
  write is check 2.11's run-owned probe — minted through the public api and
  erased on the way out — so runs may overlap each other and any suite
  (story 11.3).

A package (rather than bare modules) so pytest's prepend import mode puts the
repository root on ``sys.path`` and ``from evals.harness...`` resolves with no
path hack — the same reason ``evals/tests/`` is one.
"""
