"use strict";
// Pure-function tests for the terminal page. Run: node --test console/tests/js/
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const t = require(path.join(__dirname, "..", "..", "cerberus_terminal", "static", "terminal.js"));

const MIN = 60 * 1000;

test("tokenise splits on any run of whitespace", () => {
  assert.deepEqual(t.tokenise("  run   latest \t"), ["run", "latest"]);
  assert.deepEqual(t.tokenise("status"), ["status"]);
});

test("tokenise of blank input is empty", () => {
  assert.deepEqual(t.tokenise(""), []);
  assert.deepEqual(t.tokenise("   "), []);
});

test("tokenise does not filter hostile input", () => {
  assert.deepEqual(t.tokenise("status; id"), ["status;", "id"]);
  assert.deepEqual(t.tokenise("$(id)"), ["$(id)"]);
});

test("base64url has no padding and uses the URL alphabet", () => {
  assert.equal(t.base64url(new Uint8Array([])), "");
  assert.equal(t.base64url(new Uint8Array([0xfb, 0xff])), "-_8");
  assert.equal(t.base64url(new Uint8Array([102])), "Zg");
  assert.equal(t.base64url(new Uint8Array([102, 111])), "Zm8");
});

test("randomString of 16 bytes is 22 characters of the URL alphabet", () => {
  const s = t.randomString(16);
  assert.match(s, /^[A-Za-z0-9_-]{22}$/);
});

test("PKCE S256 challenge matches RFC 7636 appendix B", async () => {
  const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
  assert.equal(await t.pkceChallenge(verifier), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});

function saved(over) {
  return JSON.stringify({ verifier: "v", state: "s1", created: 1000, ...over });
}

test("parseCallback accepts a fresh matching callback", () => {
  const r = t.parseCallback("?code=abc&state=s1", saved(), 1000 + MIN);
  assert.deepEqual(r, { ok: true, code: "abc", verifier: "v" });
});

test("parseCallback rejects a state mismatch", () => {
  const r = t.parseCallback("?code=abc&state=other", saved(), 1000 + MIN);
  assert.equal(r.ok, false);
  assert.equal(r.reason, "state-mismatch");
});

test("parseCallback rejects a callback older than 5 minutes", () => {
  const r = t.parseCallback("?code=abc&state=s1", saved(), 1000 + 5 * MIN + 1);
  assert.equal(r.ok, false);
  assert.equal(r.reason, "too-old");
});

test("parseCallback accepts a callback of exactly 5 minutes", () => {
  assert.equal(t.parseCallback("?code=abc&state=s1", saved(), 1000 + 5 * MIN).ok, true);
});

test("parseCallback rejects missing or broken saved state", () => {
  assert.equal(t.parseCallback("?code=abc&state=s1", null, 2000).ok, false);
  assert.equal(t.parseCallback("?code=abc&state=s1", "not json", 2000).ok, false);
  assert.equal(t.parseCallback("?code=abc&state=s1", JSON.stringify({}), 2000).ok, false);
});

test("parseCallback rejects an error response and a missing code", () => {
  assert.equal(t.parseCallback("?error=access_denied&state=s1", saved(), 2000).ok, false);
  assert.equal(t.parseCallback("?state=s1", saved(), 2000).ok, false);
});

function jwt(payload) {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return enc({ alg: "none" }) + "." + enc(payload) + ".sig";
}

test("decodeExpMs reads exp in milliseconds, and null for junk", () => {
  assert.equal(t.decodeExpMs(jwt({ exp: 1700000000 })), 1700000000000);
  assert.equal(t.decodeExpMs(jwt({})), null);
  assert.equal(t.decodeExpMs("junk"), null);
  assert.equal(t.decodeExpMs(""), null);
});

test("deadline is the earlier of sign-in + 60 minutes and exp", () => {
  const signIn = 5_000_000;
  assert.equal(t.deadline(signIn, signIn + 90 * MIN), signIn + 60 * MIN);
  assert.equal(t.deadline(signIn, signIn + 30 * MIN), signIn + 30 * MIN);
  assert.equal(t.deadline(signIn, null), signIn + 60 * MIN);
});

test("idle cut-over is at exactly 15 minutes", () => {
  const last = 9_000_000;
  assert.equal(t.idleExpired(last, last + 15 * MIN - 1), false);
  assert.equal(t.idleExpired(last, last + 15 * MIN), true);
});

test("limits are 15 and 60 minutes", () => {
  assert.equal(t.IDLE_MS, 15 * MIN);
  assert.equal(t.LIMIT_MS, 60 * MIN);
});

test("validateConfig checks the auth domain and the client id", () => {
  const ok = { client_id: "abc123", auth_domain: "https://x-y.auth.us-east-1.amazoncognito.com" };
  assert.equal(t.validateConfig(ok), true);
  assert.equal(t.validateConfig({ ...ok, client_id: "ABC" }), false);
  assert.equal(t.validateConfig({ ...ok, client_id: "" }), false);
  assert.equal(t.validateConfig({ ...ok, auth_domain: "http://x.auth.us-east-1.amazoncognito.com" }), false);
  assert.equal(
    t.validateConfig({ ...ok, auth_domain: "https://x.auth.us-east-1.amazoncognito.com.evil.example" }),
    false,
  );
  assert.equal(t.validateConfig({ ...ok, auth_domain: "https://x.auth.eu-west-1.amazoncognito.com" }), false);
  assert.equal(t.validateConfig(null), false);
  assert.equal(t.validateConfig({}), false);
});

test("interpret maps statuses to the fixed messages", () => {
  assert.deepEqual(t.interpret(401, ""), { text: "Session expired. Sign in again.", end: true });
  assert.equal(t.interpret(429, "").text, "Too many commands. Wait a second.");
  assert.equal(t.interpret(500, "{}").text, "Not available right now.");
  assert.equal(t.interpret(200, "<html>").text, "Not available right now.");
  for (const status of [200, 400, 404, 503]) {
    assert.equal(t.interpret(status, JSON.stringify({ ok: false, text: "hello" })).text, "hello");
  }
});

test("complete finishes a unique prefix and a common prefix", () => {
  const names = ["help", "status", "runs", "run", "cost", "dq", "slo"];
  assert.equal(t.complete("he", names), "help");
  assert.equal(t.complete("ru", names), "run");
  assert.equal(t.complete("run", names), "run");
  assert.equal(t.complete("x", names), null);
  assert.equal(t.complete("", names), null);
  assert.equal(t.complete("run latest", names), null);
});

test("minutesLeft rounds up and never goes below zero", () => {
  assert.equal(t.minutesLeft(60 * MIN), 60);
  assert.equal(t.minutesLeft(1), 1);
  assert.equal(t.minutesLeft(-5), 0);
});
