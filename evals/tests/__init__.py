"""Eval-harness test suite.

A package (rather than bare test modules) so pytest's prepend import mode puts
the repository root on sys.path and ``from evals.harness...`` resolves without
a conftest path hack.
"""
