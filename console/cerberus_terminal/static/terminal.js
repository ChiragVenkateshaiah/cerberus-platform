/* Cerberus terminal (ADR 0024 amendment, 2026-11-12). A plain DOM terminal.
 *
 * Rules this file keeps (console/tests/test_terminal_js_scan.py checks them):
 * - Output goes in with textContent and createElement only.
 * - The access token lives in the variable `token`. Nothing else is stored.
 * - sessionStorage holds two keys: PKCE_KEY (during the sign-in redirect) and ENDED_KEY.
 * - No element.style, no inline style, no eval, no localStorage.
 * - The page never filters input. The server is the only judge.
 */
"use strict";

const IDLE_MS = 15 * 60 * 1000;
const LIMIT_MS = 60 * 60 * 1000;
const PKCE_MAX_AGE_MS = 5 * 60 * 1000;
const CHECK_MS = 15 * 1000;
const REQUEST_TIMEOUT_MS = 30 * 1000;
const PKCE_KEY = "cerberus-pkce";
const ENDED_KEY = "cerberus-ended";
const API_PATH = "/api/command";
const CONFIG_PATH = "config.json";
const COMMAND_NAMES = ["help", "status", "runs", "run", "cost", "dq", "slo"];
const AUTH_DOMAIN_RE = /^https:\/\/[a-z0-9-]+\.auth\.us-east-1\.amazoncognito\.com$/;
const CLIENT_ID_RE = /^[a-z0-9]{1,128}$/;

const ENDED_TEXT = {
  idle: "Session ended (15 minutes idle). Sign in again.",
  limit: "Session ended (60-minute limit). Sign in again.",
  signout: "Signed out.",
  expired: "Session expired. Sign in again.",
};

/* ---- Pure functions (exported for the Node tests) ---- */

function tokenise(line) {
  const trimmed = line.trim();
  return trimmed === "" ? [] : trimmed.split(/\s+/);
}

function base64url(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(byteCount) {
  const bytes = new Uint8Array(byteCount);
  globalThis.crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function pkceChallenge(verifier) {
  const data = new TextEncoder().encode(verifier);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
  return base64url(new Uint8Array(digest));
}

/* The state check and the age check. `stored` is the raw sessionStorage text. */
function parseCallback(search, stored, now) {
  const params = new URLSearchParams(search);
  if (params.get("error")) return { ok: false, reason: "error" };
  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) return { ok: false, reason: "missing" };
  let saved;
  try {
    saved = JSON.parse(stored);
  } catch (err) {
    return { ok: false, reason: "no-saved-state" };
  }
  if (!saved || typeof saved.verifier !== "string" || typeof saved.state !== "string") {
    return { ok: false, reason: "no-saved-state" };
  }
  if (typeof saved.created !== "number" || now - saved.created > PKCE_MAX_AGE_MS) {
    return { ok: false, reason: "too-old" };
  }
  if (saved.state !== state) return { ok: false, reason: "state-mismatch" };
  return { ok: true, code: code, verifier: saved.verifier };
}

/* The exp claim of a JWT, in milliseconds. For the timer only. Not trusted for auth. */
function decodeExpMs(jwt) {
  try {
    const part = String(jwt).split(".")[1];
    const padded = part.replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
    const exp = JSON.parse(json).exp;
    return typeof exp === "number" && Number.isFinite(exp) ? exp * 1000 : null;
  } catch (err) {
    return null;
  }
}

function deadline(signInAt, expMs) {
  const limit = signInAt + LIMIT_MS;
  return expMs === null || expMs === undefined ? limit : Math.min(limit, expMs);
}

function idleExpired(lastActivity, now) {
  return now - lastActivity >= IDLE_MS;
}

function validateConfig(cfg) {
  if (!cfg || typeof cfg.auth_domain !== "string" || typeof cfg.client_id !== "string") {
    return false;
  }
  return AUTH_DOMAIN_RE.test(cfg.auth_domain) && CLIENT_ID_RE.test(cfg.client_id);
}

function interpret(status, bodyText) {
  if (status === 401) return { text: "Session expired. Sign in again.", end: true };
  if (status === 429) return { text: "Too many commands. Wait a second.", end: false };
  if (status === 200 || status === 400 || status === 404 || status === 503) {
    try {
      const body = JSON.parse(bodyText);
      if (body && typeof body.text === "string") return { text: body.text, end: false };
    } catch (err) {
      /* fall through */
    }
  }
  return { text: "Not available right now.", end: false };
}

function complete(line, names) {
  if (line === "" || /\s/.test(line)) return null;
  const hits = names.filter((n) => n.startsWith(line));
  if (hits.length === 0) return null;
  if (hits.length === 1 || names.includes(line)) return hits.length === 1 ? hits[0] : line;
  let prefix = hits[0];
  for (const h of hits) {
    while (!h.startsWith(prefix)) prefix = prefix.slice(0, -1);
  }
  return prefix.length > line.length ? prefix : null;
}

function minutesLeft(ms) {
  return Math.max(0, Math.ceil(ms / 60000));
}

/* ---- Page code ---- */

let token = null;

function start() {
  const els = {
    log: document.getElementById("log"),
    status: document.getElementById("status"),
    form: document.getElementById("cmd-form"),
    input: document.getElementById("cmd-input"),
    signIn: document.getElementById("sign-in"),
    signOut: document.getElementById("sign-out"),
  };
  let cfg = null;
  let signInAt = 0;
  let expMs = null;
  let lastActivity = 0;
  let timer = null;
  let inFlight = false;
  const past = [];
  let pastPos = 0;

  function print(text, cls) {
    const line = document.createElement("div");
    line.className = cls ? "line " + cls : "line";
    line.textContent = text;
    els.log.append(line);
    els.log.scrollTop = els.log.scrollHeight;
  }

  function setSignedIn(on) {
    els.form.hidden = !on;
    els.signOut.hidden = !on;
    els.signIn.hidden = on || cfg === null;
  }

  function logoutUrl() {
    const q = new URLSearchParams({
      client_id: cfg.client_id,
      logout_uri: location.origin + "/terminal/index.html",
    });
    return cfg.auth_domain + "/logout?" + q.toString();
  }

  function end(reason) {
    token = null;
    els.input.disabled = true;
    if (timer !== null) clearInterval(timer);
    try {
      sessionStorage.setItem(ENDED_KEY, reason);
    } catch (err) {
      /* storage blocked: the logout still happens */
    }
    location.assign(logoutUrl());
  }

  /* Wall-clock check. Returns false when the session has just ended. */
  function tick() {
    if (token === null) return false;
    const now = Date.now();
    const limit = deadline(signInAt, expMs);
    if (now >= limit) {
      end("limit");
      return false;
    }
    if (idleExpired(lastActivity, now)) {
      end("idle");
      return false;
    }
    const left = minutesLeft(limit - now);
    const idle = minutesLeft(lastActivity + IDLE_MS - now);
    els.status.textContent =
      "Signed in. " + left + " min left in the session. Idle drop in " + idle + " min.";
    return true;
  }

  async function send(argv) {
    const ctrl = new AbortController();
    const abortTimer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
    inFlight = true;
    try {
      const res = await fetch(API_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ argv: argv }),
        signal: ctrl.signal,
      });
      const out = interpret(res.status, await res.text());
      print(out.text);
      if (out.end) end("expired");
    } catch (err) {
      print("Not available right now.");
    } finally {
      clearTimeout(abortTimer);
      inFlight = false;
    }
  }

  function onSubmit(event) {
    event.preventDefault();
    if (!tick() || inFlight) return;
    const line = els.input.value;
    const argv = tokenise(line);
    if (argv.length === 0) return;
    lastActivity = Date.now();
    past.push(line);
    pastPos = past.length;
    els.input.value = "";
    if (argv.length === 1 && argv[0] === "clear") {
      els.log.replaceChildren();
      return;
    }
    print("> " + line, "echo");
    send(argv);
  }

  function onKeydown(event) {
    if (!tick()) return;
    lastActivity = Date.now();
    if (event.key === "ArrowUp" && pastPos > 0) {
      event.preventDefault();
      pastPos -= 1;
      els.input.value = past[pastPos];
    } else if (event.key === "ArrowDown" && pastPos < past.length) {
      event.preventDefault();
      pastPos += 1;
      els.input.value = pastPos === past.length ? "" : past[pastPos];
    } else if (event.key === "Tab") {
      const hit = complete(els.input.value, COMMAND_NAMES);
      if (hit !== null) {
        event.preventDefault();
        els.input.value = COMMAND_NAMES.includes(hit) ? hit + " " : hit;
      }
    }
  }

  function begin(accessToken) {
    token = accessToken;
    signInAt = Date.now();
    lastActivity = signInAt;
    expMs = decodeExpMs(accessToken);
    setSignedIn(true);
    print("Type help for the list of commands. Type clear to clear the screen.");
    tick();
    timer = setInterval(tick, CHECK_MS);
    document.addEventListener("visibilitychange", tick);
    window.addEventListener("focus", tick);
    els.form.addEventListener("submit", onSubmit);
    els.input.addEventListener("keydown", onKeydown);
    els.input.focus();
  }

  async function signIn() {
    const verifier = randomString(32);
    const state = randomString(16);
    const challenge = await pkceChallenge(verifier);
    sessionStorage.setItem(
      PKCE_KEY,
      JSON.stringify({ verifier: verifier, state: state, created: Date.now() }),
    );
    const q = new URLSearchParams({
      response_type: "code",
      client_id: cfg.client_id,
      redirect_uri: location.origin + "/terminal/index.html",
      scope: "openid",
      state: state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    location.assign(cfg.auth_domain + "/oauth2/authorize?" + q.toString());
  }

  async function exchange(code, verifier) {
    const tokenUrl = cfg.auth_domain + "/oauth2/token";
    const res = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: cfg.client_id,
        code: code,
        redirect_uri: location.origin + "/terminal/index.html",
        code_verifier: verifier,
      }).toString(),
    });
    if (!res.ok) throw new Error("token exchange failed");
    const body = await res.json();
    if (typeof body.access_token !== "string") throw new Error("no access token");
    return body.access_token;
  }

  async function main() {
    els.signIn.addEventListener("click", () => {
      els.signIn.disabled = true;
      signIn().catch(() => {
        els.signIn.disabled = false;
        print("Sign-in could not start.");
      });
    });
    els.signOut.addEventListener("click", () => {
      if (token !== null) end("signout");
    });
    setSignedIn(false);

    let ended = null;
    try {
      ended = sessionStorage.getItem(ENDED_KEY);
      sessionStorage.removeItem(ENDED_KEY);
    } catch (err) {
      ended = null;
    }

    try {
      const res = await fetch(CONFIG_PATH);
      const parsed = res.ok ? await res.json() : null;
      if (!validateConfig(parsed)) throw new Error("bad config");
      cfg = parsed;
    } catch (err) {
      els.status.textContent = "The terminal is not configured. Try again later.";
      return;
    }

    if (ended !== null && Object.prototype.hasOwnProperty.call(ENDED_TEXT, ended)) {
      print(ENDED_TEXT[ended]);
    }

    const search = location.search;
    if (search.includes("code=") || search.includes("error=")) {
      let stored = null;
      try {
        stored = sessionStorage.getItem(PKCE_KEY);
        sessionStorage.removeItem(PKCE_KEY);
      } catch (err) {
        stored = null;
      }
      window.history.replaceState(null, "", location.pathname);
      const cb = parseCallback(search, stored, Date.now());
      if (cb.ok) {
        try {
          begin(await exchange(cb.code, cb.verifier));
          return;
        } catch (err) {
          print("Sign-in failed. Sign in again.");
        }
      } else {
        print("Sign-in failed. Sign in again.");
      }
    }
    setSignedIn(false);
    els.status.textContent = "Not signed in.";
  }

  main();
}

if (typeof module !== "undefined") {
  module.exports = {
    IDLE_MS,
    LIMIT_MS,
    PKCE_MAX_AGE_MS,
    tokenise,
    base64url,
    randomString,
    pkceChallenge,
    parseCallback,
    decodeExpMs,
    deadline,
    idleExpired,
    validateConfig,
    interpret,
    complete,
    minutesLeft,
  };
}

if (typeof document !== "undefined") {
  start();
}
