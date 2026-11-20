"""The headless-browser parts. Playwright is imported inside functions only (CI has none).

No tracing, no video, no HAR. Each part gets a new browser context, so it starts from a
clean profile. A screenshot is never taken on a Cognito page. The password is passed to
`cognito_login` and nowhere else: it is not stored in a check, a note or a log line.
"""

import contextlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from cerberus_console import grammar
from cerberus_live_check import http
from cerberus_live_check.report import Check, Typed, commands

COGNITO_HOST = "amazoncognito.com"
NAV_BANNED = ("explore", "cfg", "admin")
STORY_PANELS = ("Now", "Data quality result", "Clean-up result")
WINDOWS = ("2026-10-13", "2026-11-08 14:26")
GAP_S = 1.6  # throttle is 1 request a second, burst 3: stay under it
CMD_WAIT_S = 30

_FETCH_JS = """async ([path, method, body]) => {
  const opts = {method: method, credentials: 'same-origin', headers: {}};
  if (body !== null) { opts.body = body; opts.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, opts);
  return {status: r.status, text: (await r.text()).slice(0, 200000)};
}"""

_BOOT_JS = """() => {
  const b = window.grafanaBootData;
  if (!b) return null;
  const ids = [];
  const walk = (n) => {
    if (!n) return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (typeof n === 'object') { if (n.id) ids.push(String(n.id)); walk(n.children); }
  };
  walk(b.navTree);
  return {
    orgRole: b.user ? b.user.orgRole : null,
    isGrafanaAdmin: b.user ? b.user.isGrafanaAdmin : null,
    disableLoginForm: b.settings ? b.settings.disableLoginForm : null,
    exploreEnabled: b.settings ? b.settings.exploreEnabled : null,
    navIds: ids,
  };
}"""


def find_chromium(arg: str | None) -> str | None:
    """--chromium, else $CERBERUS_CHROMIUM, else the newest headless shell in the cache."""
    chosen = arg or os.environ.get("CERBERUS_CHROMIUM")
    if chosen:
        return chosen
    cache = Path.home() / ".cache" / "ms-playwright"
    found = sorted(
        cache.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")
    )
    return str(found[-1]) if found else None


@contextmanager
def launched(chromium: str | None):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium) if chromium else pw.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


class Watched:
    """A page plus the things every page is watched for: CSP violations and dialogs."""

    def __init__(self, browser):
        self.context = browser.new_context(viewport={"width": 1100, "height": 800})
        self.page = self.context.new_page()
        self.csp: list[str] = []
        self.dialogs: list[str] = []
        self.page.on("console", self._console)
        self.page.on("dialog", self._dialog)

    def _console(self, message):
        if "content security policy" in message.text.lower():
            self.csp.append(message.text[:200])

    def _dialog(self, dialog):
        self.dialogs.append(dialog.type)
        dialog.dismiss()

    def close(self):
        self.context.close()


def shot(page, outdir: Path, name: str) -> str:
    """Full-page screenshot, never on a Cognito page. Returns the file name or ''."""
    if COGNITO_HOST in page.url:
        return ""
    path = outdir / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def _safe(check_id: str, expected: str, fn) -> Check:
    """Run one check body; a raised error is a fail that names only the error type."""
    try:
        return fn()
    except Exception as err:  # a broken selector must not stop the other checks
        return Check(
            check_id, "fail", expected, f"error {type(err).__name__}", str(err).split("\n")[0][:160]
        )


def csp_checks(browser, pages: dict[str, str], outdir: Path) -> list[Check]:
    """D2: no CSP violation while a page loads (before sign-in)."""
    checks = []
    for label, url in pages.items():

        def one(url=url, label=label):
            w = Watched(browser)
            try:
                w.page.goto(url, wait_until="networkidle", timeout=45000)
                png = shot(w.page, outdir, f"d2-{label}")
                status = "pass" if not w.csp else "fail"
                return Check(f"D2 {label}", status, "0 CSP violations", f"{len(w.csp)}", png)
            finally:
                w.close()

        checks.append(_safe(f"D2 {label}", "0 CSP violations", one))
    return checks


def on_cognito(url: str) -> bool:
    """True when the URL host is the Cognito hosted UI (the host, not a query string)."""
    return (urlsplit(url).hostname or "").endswith(COGNITO_HOST)


def cognito_login(page, user: str, password: str) -> None:
    page.wait_for_url(on_cognito, timeout=30000)
    name = page.locator("input[name=username]:visible").first
    name.fill(user)
    secret = page.locator("input[name=password]:visible").first
    secret.fill(password)
    secret.press("Enter")


def _new_lines(page, before: int) -> list[str]:
    texts = page.eval_on_selector_all("#log .line", "els => els.map(e => e.textContent)")
    return texts[before:]


def _submit(page) -> list[str]:
    """Press Enter and collect the new lines: the echo, then the reply."""
    before = page.locator("#log .line").count()
    page.press("#cmd-input", "Enter")
    with contextlib.suppress(Exception):
        page.wait_for_function(
            "n => document.querySelectorAll('#log .line').length >= n",
            arg=before + 2,
            timeout=CMD_WAIT_S * 1000,
        )
    time.sleep(GAP_S)
    return _new_lines(page, before)


def _reply(lines: list[str]) -> list[str]:
    return [t for t in lines if not t.startswith("> ")]


def terminal_checks(
    browser, standing: str, user: str, password: str, outdir: Path, typed: list[Typed]
) -> list[Check]:
    """D3a to D3d: sign in at the terminal, run the commands, type the hostile lines, sign out."""
    checks: list[Check] = []
    w = Watched(browser)
    try:
        page = w.page
        try:
            page.goto(f"{standing.rstrip('/')}/terminal/index.html", wait_until="networkidle")
            page.click("#sign-in")
            cognito_login(page, user, password)
            page.wait_for_function(
                "() => document.getElementById('status').textContent.startsWith('Signed in.')",
                timeout=60000,
            )
        except Exception as err:
            checks.append(
                Check(
                    "D3a", "fail", "status starts with 'Signed in.'", f"error {type(err).__name__}"
                )
            )
            return checks
        status_text = page.inner_text("#status")
        checks.append(Check("D3a", "pass", "status starts with 'Signed in.'", status_text[:60]))

        bad = {
            grammar.REFUSED_TEXT,
            "Not available right now.",
            "Too many commands. Wait a second.",
        }
        for cmd in commands():
            page.fill("#cmd-input", cmd)
            reply = _reply(_submit(page))
            ok = bool(reply) and not any(t in bad for t in reply)
            checks.append(
                Check(
                    f"D3b {cmd}",
                    "pass" if ok else "fail",
                    "a reply that is not a refusal",
                    f"{len(reply)} line(s)",
                    (reply[0][:60] if reply else ""),
                )
            )

        for t in typed:
            checks.append(_typed_check(w, t, outdir))

        shot(page, outdir, "d3-terminal")
        checks.append(_sign_out(page, standing))
        checks.append(
            Check(
                "D2 signed-in", "pass" if not w.csp else "fail", "0 CSP violations", f"{len(w.csp)}"
            )
        )
    finally:
        w.close()
    return checks


def _sign_out(page, standing: str) -> Check:
    """D3d: Cognito logout, then back on the terminal page, then the signed-out state."""
    expected = "Cognito logout, back on the terminal page, signed out"
    host = urlsplit(standing).hostname
    step = "click"
    try:
        page.click("#sign-out")
        step = "reach the Cognito logout"
        page.wait_for_url(on_cognito, timeout=30000)
        step = "return to the terminal host"
        page.wait_for_url(lambda u: urlsplit(u).hostname == host, timeout=30000)
        step = "show the signed-out state"
        page.wait_for_function(
            "() => !document.getElementById('sign-in').hidden"
            " || !document.getElementById('status').textContent.startsWith('Signed in.')",
            timeout=30000,
        )
    except Exception as err:
        return Check("D3d", "fail", expected, f"failed to {step}", type(err).__name__)
    return Check("D3d", "pass", expected, "all three steps happened")


def _typed_check(w: Watched, t: Typed, outdir: Path) -> Check:
    def one():
        page = w.page
        page.fill("#cmd-input", "")
        page.focus("#cmd-input")
        page.keyboard.insert_text(t.line)
        value = page.input_value("#cmd-input")
        reached = value == t.expected_value
        reply = _reply(_submit(page))
        refused = reply == [grammar.REFUSED_TEXT]
        no_img = page.locator("#log img").count() == 0
        clean = refused and no_img and not w.dialogs
        shot(page, outdir, "d3c-" + re.sub(r"\W+", "-", t.name))
        status = "pass" if clean and reached else ("fail" if not clean else "record")
        note = f"input reached the page exactly: {reached}; value length {len(value)}"
        return Check(
            f"D3c {t.name}", status, "fixed refusal, no dialog, no img", f"{reply[:1]}", note
        )

    return _safe(f"D3c {t.name}", "fixed refusal", one)


def _page_fetch(page, path: str, method: str = "GET", body: str | None = None) -> dict:
    return page.evaluate(_FETCH_JS, [path, method, body])


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from _walk_strings(item)


def _grafana_page(browser, session: str, user: str, password: str) -> Watched:
    """A new context, signed in through Cognito, landed on the Grafana home."""
    w = Watched(browser)
    w.page.goto(session, wait_until="domcontentloaded")
    if COGNITO_HOST in w.page.url or "/login" in w.page.url:
        with contextlib.suppress(Exception):
            cognito_login(w.page, user, password)
        host = urlsplit(session).hostname
        w.page.wait_for_url(lambda u: urlsplit(u).hostname == host, timeout=60000)
    w.page.wait_for_load_state("networkidle", timeout=60000)
    return w


def grafana_checks(browser, session: str, user: str, password: str, outdir: Path) -> list[Check]:
    """E1 to E6 against the session Grafana. An unverified selector gives 'record'."""
    base = session.rstrip("/")
    checks: list[Check] = []
    try:
        w = _grafana_page(browser, session, user, password)
    except Exception as err:
        return [Check("E1", "fail", "Cognito then Grafana", f"error {type(err).__name__}")]
    try:
        page = w.page
        checks += _e1(page, session)
        checks += _e2_e6(w, base, outdir, page)
        checks += _e4(page)
    finally:
        w.close()
    checks += _e5(browser, base, session, user, password)
    return checks


def _e1(page, session: str) -> list[Check]:
    def one():
        pw_fields = page.locator("input[type=password]").count()
        boot = page.evaluate(_BOOT_JS)
        out = [
            Check(
                "E1a",
                "pass" if pw_fields == 0 else "fail",
                "no password field on the session origin",
                str(pw_fields),
            )
        ]
        if boot is None:
            out.append(Check("E1b", "record", "grafanaBootData", "missing", "unverified key names"))
            return out
        ids = boot["navIds"]
        banned = [i for i in ids if i in NAV_BANNED or i.startswith(("cfg", "admin"))]
        ok = (
            boot["orgRole"] == "Viewer"
            and boot["isGrafanaAdmin"] is False
            and boot["disableLoginForm"] is True
            and not banned
        )
        seen = json.dumps(
            {
                k: boot[k]
                for k in ("orgRole", "isGrafanaAdmin", "disableLoginForm", "exploreEnabled")
            }
        )
        out.append(
            Check(
                "E1b",
                "pass" if ok else "fail",
                "Viewer, not admin, login form off, no cfg/admin/explore",
                seen,
                f"{len(ids)} nav ids; banned: {banned}",
            )
        )
        return out

    got = _safe("E1", "boot data", lambda: one())
    return got if isinstance(got, list) else [got]


def _e2_e6(w: Watched, base: str, outdir: Path, page) -> list[Check]:
    checks: list[Check] = []
    try:
        reply = _page_fetch(page, "/api/dashboards/uid/cerberus-runs")
        links = re.findall(
            r"\[([^\]]+)\]\((/d/cerberus-run-story\?[^)]+)\)",
            "\n".join(_walk_strings(json.loads(reply["text"]))),
        )
    except Exception as err:
        return [
            Check(
                "E2",
                "fail",
                "the home dashboard lists the recorded runs",
                f"error {type(err).__name__}",
            )
        ]
    first_query = ""
    for label in WINDOWS:
        match = next(((t, p) for t, p in links if label in t), None)
        if match is None:
            checks.append(Check(f"E2 {label}", "fail", "a link for the window", "not found"))
            continue
        path = match[1]
        first_query = first_query or path
        checks += _window(w, base, path, label, outdir)
    checks += _e3(page, base, first_query, outdir)
    return checks


def _window(w: Watched, base: str, path: str, label: str, outdir: Path) -> list[Check]:
    def one():
        started: dict = {}
        queries: list[tuple[int, float, bool]] = []
        annotations: list[int] = []

        def on_request(req):
            started[req] = time.monotonic()

        def on_response(res):
            url = res.url
            if "/api/ds/query" in url:
                took = time.monotonic() - started.get(res.request, time.monotonic())
                full = False
                with contextlib.suppress(Exception):
                    body = res.json()
                    full = any(
                        v.get("frames")
                        and any(f.get("data", {}).get("values") for f in v["frames"])
                        for v in body.get("results", {}).values()
                    )
                queries.append((res.status, took, full))
            elif "/api/annotations" in url:
                with contextlib.suppress(Exception):
                    annotations.append(len(res.json()))

        tab = w.context.new_page()
        tab.on("request", on_request)
        tab.on("response", on_response)
        tab.goto(base + path, wait_until="domcontentloaded")
        with contextlib.suppress(Exception):
            tab.wait_for_load_state("networkidle", timeout=60000)
        tiles = {}
        for title in STORY_PANELS:
            sel = tab.locator(f'[data-testid="data-testid Panel header {title}"]')
            tiles[title] = (
                "selector missed"
                if sel.count() == 0
                else ("No data" if "No data" in sel.first.inner_text() else "data")
            )
        png = shot(tab, outdir, "e2-" + re.sub(r"\W+", "-", label))
        tab.close()
        by_status: dict[int, int] = {}
        for status, _took, _full in queries:
            by_status[status] = by_status.get(status, 0) + 1
        slowest = max((t for _s, t, _f in queries), default=0.0)
        n_ann = max(annotations, default=0)
        return [
            Check(
                f"E2 {label}",
                "pass" if n_ann > 0 and by_status.get(200, 0) > 0 else "fail",
                "ds/query 200, annotations > 0",
                f"ds/query by status {by_status}; non-empty {sum(1 for *_x, f in queries if f)}; "
                f"annotations {n_ann}",
                png,
            ),
            Check(f"E2 tiles {label}", "record", "tiles filled", json.dumps(tiles)),
            Check(
                f"E6 {label}",
                "pass" if by_status.get(504, 0) == 0 else "fail",
                "0 x 504",
                f"504 count {by_status.get(504, 0)}; slowest ds/query {slowest:.1f}s",
            ),
        ]

    got = _safe(f"E2 {label}", "window loads", one)
    return got if isinstance(got, list) else [got]


def _e3(page, base: str, story_path: str, outdir: Path) -> list[Check]:
    def one():
        query = urlsplit(story_path).query if story_path else ""
        join = f"{query}&" if query else ""
        tab = page.context.new_page()
        tab.goto(
            f"{base}/d/cerberus-run-story?{join}inspect=4&inspectTab=query",
            wait_until="domcontentloaded",
        )
        with contextlib.suppress(Exception):
            tab.wait_for_load_state("networkidle", timeout=60000)
        drawer = tab.locator('[role="dialog"], [data-testid*="drawer" i]').count() > 0
        png = shot(tab, outdir, "e3-inspect")
        tab.close()
        ex = page.context.new_page()
        resp = ex.goto(base + "/explore", wait_until="domcontentloaded")
        status = resp.status if resp else 0
        final = urlsplit(ex.url).path
        ex.close()
        boot = page.evaluate(_BOOT_JS) or {}
        return [
            Check(
                "E3 inspect",
                "record",
                "the Query inspect drawer opens for a Viewer",
                f"drawer visible: {drawer}",
                png,
            ),
            Check(
                "E3 explore",
                "fail" if boot.get("exploreEnabled") is True else "record",
                "Explore is not available",
                f"exploreEnabled {boot.get('exploreEnabled')}; /explore status {status}; "
                f"ends at {final}",
            ),
        ]

    got = _safe("E3", "inspect and explore", one)
    return got if isinstance(got, list) else [got]


def _e4(page) -> list[Check]:
    def one():
        out = []
        for path in ("/api/user", "/api/frontend/settings", "/api/datasources"):
            reply = _page_fetch(page, path)
            leak = re.search(r"(?<!\d)\d{12}(?!\d)|arn:aws", reply["text"])
            out.append(
                Check(
                    f"E4 {path}",
                    "fail" if leak else "record",
                    "no account ID or ARN in the body",
                    f"status {reply['status']}",
                    "leak found" if leak else "",
                )
            )
        body = json.dumps(
            {
                "queries": [{"refId": "A", "datasource": {"uid": "cloudwatch"}}],
                "from": "now-5m",
                "to": "now",
            }
        )
        reply = _page_fetch(page, "/api/ds/query", "POST", body)
        ok = not 200 <= reply["status"] < 300
        out.append(
            Check(
                "E4 cloudwatch ds/query",
                "pass" if ok else "fail",
                "not 2xx",
                f"status {reply['status']}",
            )
        )
        return out

    got = _safe("E4", "api reads", one)
    return got if isinstance(got, list) else [got]


def _e5(browser, base: str, session: str, user: str, password: str) -> list[Check]:
    def one():
        w = _grafana_page(browser, session, user, password)
        try:
            chain: list[str] = []
            w.page.on("framenavigated", lambda f: chain.append(urlsplit(f.url).path))
            with contextlib.suppress(Exception):
                w.page.goto(base + "/logout", wait_until="networkidle", timeout=45000)
            saw_login = any(p.startswith("/login") for p in chain)
            w.page.goto(session, wait_until="domcontentloaded")
            with contextlib.suppress(Exception):
                w.page.wait_for_url(on_cognito, timeout=30000)
            at_cognito = on_cognito(w.page.url)
            asks = at_cognito and w.page.locator("input[name=password]:visible").count() > 0
            return [
                Check(
                    "E5",
                    "pass" if asks else "fail",
                    "logout passes /login; the next visit asks for the password",
                    f"/login in chain: {saw_login}; password asked: {asks}",
                )
            ]
        finally:
            w.close()

    got = _safe("E5", "logout", one)
    return got if isinstance(got, list) else [got]


def probe_bodies(url: str) -> list[Check]:
    """D1b to D1d over plain HTTP (no browser). The POSTs carry no token."""
    api = f"{url.rstrip('/')}/api/command"
    body = json.dumps({"argv": ["status"]}).encode()
    heads = {"Content-Type": "application/json"}
    checks = []
    for cid, extra in (("D1b no token", {}), ("D1c Bearer x", {"Authorization": "Bearer x"})):
        status, _h, _b = http.fetch(api, "POST", body, {**heads, **extra})
        checks.append(Check(cid, "pass" if status == 401 else "fail", "401", str(status)))
    status, _h, _b = http.fetch(api, "GET")
    checks.append(Check("D1d GET", "record", "404 (2026-11-14)", str(status)))
    return checks
