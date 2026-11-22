"""Agents package (ADR 0025). 14.2a: the model-free review core.

It imports `cerberus_console` (sanitising, config, grammar, records), so
`console/` must be on `sys.path`: PYTHONPATH in `make verify` and CI, and
`agents/tests/conftest.py` for a bare pytest run.
"""
