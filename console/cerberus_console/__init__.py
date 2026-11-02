"""Cerberus 9.3 -- the read-only console command set (ADR 0024).

One package serves two entry points: the local CLI (`python -m cerberus_console`,
later `make status`, ADR 0021) and the Lambda handler that step 7 puts behind the
console site (`cerberus_console.api.lambda_handler`). See console/README.md.
"""
