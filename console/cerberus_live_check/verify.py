"""The `verify` run: public checks first, then the sign-in checks. Read-only."""

import getpass
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from cerberus_live_check import browser, http, shared, watch
from cerberus_live_check.report import Check, compare_headers, stamp, typed_lines, write

REPORTS_DIR = Path(__file__).resolve().parents[1] / "live-check-reports"
USER_ENV = "CERBERUS_CHECK_USER"
PASSWORD_ENV = "CERBERUS_CHECK_PASSWORD"  # noqa: S105  (the name of a variable, not a secret)
DEFAULT_USER = "console-check"
STAMP_FORMAT = "%Y-%m-%dT%H:%MZ"


def get_password(no_sign_in: bool) -> str | None:
    """The password from the environment or getpass; None when sign-in checks are off."""
    if no_sign_in:
        return None
    value = os.environ.get(PASSWORD_ENV)
    if value:
        return value
    if sys.stdin.isatty():
        return getpass.getpass(f"Password for {os.environ.get(USER_ENV, DEFAULT_USER)}: ") or None
    return None


def public_checks(standing: str, session: str | None, chromium, outdir: Path) -> list[Check]:
    checks: list[Check] = []
    page_url = f"{standing.rstrip('/')}/terminal/index.html"

    status, headers, _body = http.fetch(page_url)
    if status == 200:
        checks.append(compare_headers(headers, shared.edge_headers()))
    else:
        checks.append(Check("D1a", "fail", "200 on /terminal/index.html", str(status)))
    checks += browser.probe_bodies(standing)

    pages = {"landing": f"{standing.rstrip('/')}/", "terminal": page_url}
    try:
        with browser.launched(chromium) as launched:
            checks += browser.csp_checks(launched, pages, outdir)
    except Exception as err:
        checks.append(
            Check(
                "D2",
                "fail",
                "a browser launches",
                f"error {type(err).__name__}",
                str(err).split("\n")[0][:160],
            )
        )

    hosts = {"standing": http.host_of(standing)}
    if session:
        hosts["session"] = http.host_of(session)
    for label, host in hosts.items():
        result = http.tls_probe(host)
        checks.append(
            Check(
                f"T1 {label}",
                "record",
                "record: default certificate (ADR 0026 5a)",
                "; ".join(f"{k} {v}" for k, v in result.items()),
            )
        )
    if session:
        status, headers, _b = http.fetch(session, follow=True)
        keep = (
            "strict-transport-security",
            "content-security-policy",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
        )
        seen = {k: headers[k] for k in keep if k in headers}
        checks.append(
            Check(
                "S1",
                "record",
                "session response security headers (ADR 0026 5d)",
                f"status {status}; {seen}",
            )
        )
    return checks


def run(args) -> int:
    started = datetime.now(UTC)
    password = get_password(args.no_sign_in)
    standing = args.standing.rstrip("/")
    outdir = Path(args.out) if args.out else REPORTS_DIR / stamp()
    outdir.mkdir(parents=True, exist_ok=True)
    chromium = browser.find_chromium(args.chromium)
    checks: list[Check] = []

    session = None
    if args.no_wait:
        status, ready, info, reason = watch.read_live(standing)
        checks.append(
            Check(
                "L1", "pass" if ready else "fail", "live.json 200 and ready", f"{status}: {reason}"
            )
        )
    else:
        info = watch.wait_ready(standing, args.timeout_min, show_url=False)
        ready = info is not None
        checks.append(
            Check(
                "L1",
                "pass" if ready else "fail",
                "live.json 200 and ready",
                "ready" if ready else "timeout",
            )
        )
    if ready:
        session = info["url"]
        left = watch.minutes_left(info["ends"])
        checks[-1].observed += f"; {left} min left"

    checks += public_checks(standing, session, chromium, outdir)

    user = os.environ.get(USER_ENV, DEFAULT_USER)
    if password and session:
        try:
            with browser.launched(chromium) as launched:
                checks += browser.terminal_checks(
                    launched, standing, user, password, outdir, typed_lines()
                )
                checks += browser.grafana_checks(launched, session, user, password, outdir)
        except Exception as err:
            checks.append(
                Check("SIGNIN", "fail", "the browser runs", f"error {type(err).__name__}")
            )
    else:
        why = "no password" if not password else "no live session"
        checks.append(Check("D3/E1-E6", "skip", "sign-in checks", f"skip: {why}"))

    hosts = {http.host_of(standing): "<standing-cf>"}
    if session:
        hosts[http.host_of(session)] = "<session-cf>"
    meta = {
        "started": started.strftime(STAMP_FORMAT),
        "finished": datetime.now(UTC).strftime(STAMP_FORMAT),
        "sign-in": bool(password and session),
    }
    code = write(outdir, checks, password or "", hosts, meta)
    if code == 2:
        print(
            f"STOP: the password was found in the report. No report was written; the "
            f"screenshots in {outdir} never show a Cognito page.",
            file=sys.stderr,
        )
        return 2
    print(f"report: {outdir}\a", flush=True)
    return code
