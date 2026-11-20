"""Live-check harness for the 9.6 section 7 and 9.2 PR F checks (plan 2026-11-15).

Read-only. It sends HTTP GET and POST (no token) to the standing edge, probes TLS,
and drives a headless browser. It signs in only as `console-check`, with a password
from getpass or CERBERUS_CHECK_PASSWORD. It never runs a program (ADR 0024 rule 5),
and it is never deployed: the Lambda zip takes only cerberus_console/ and runs/.

Playwright is imported inside functions only, so CI (which has no Playwright)
can import every module here.
"""
