"""Harness internals: ground-truth loading and eval-subject selection.

Deliberately importless at package level. Callers reach for the module they
need (``groundtruth``, ``subjects``) so the AD-16 import walk over this
package reads as the set of things the harness actually depends on.
"""
