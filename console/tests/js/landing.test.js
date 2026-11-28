"use strict";
// Behaviour of the landing page's "follow the batch" and live link. Run: node --test console/tests/js/*.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const t = require(path.join(__dirname, "..", "..", "cerberus_landing", "static", "site.js"));

const NOW = Date.parse("2026-11-12T10:30:00Z");
const ENDS = "2026-11-12T11:30:00Z";
const HREF = "https://session.example.test/d/cerberus-runs";

function live(over) {
  return {
    schema: 1,
    url: "https://session.example.test/",
    home: "/d/cerberus-runs",
    started: "2026-11-12T10:00:00Z",
    ends: ENDS,
    ...over,
  };
}

// An <a> as the built page holds it: hidden and with no href.
function fakeLink() {
  const attrs = {};
  return {
    hidden: true,
    attrs,
    setAttribute(name, value) {
      attrs[name] = value;
    },
    removeAttribute(name) {
      delete attrs[name];
    },
  };
}

// Replaces fetch with a list of answers; the last one repeats. Returns the calls.
function stubFetch(testContext, ...answers) {
  const calls = [];
  const original = globalThis.fetch;
  testContext.after(() => {
    globalThis.fetch = original;
  });
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    const answer = answers.length > 1 ? answers.shift() : answers[0];
    if (answer instanceof Error) throw answer;
    return answer;
  };
  return calls;
}

const ok = (body) => ({ status: 200, json: async () => body });
const missing = (status) => ({
  status,
  json: async () => live(), // the body of an error reply is never used
});
const notJson = {
  status: 200,
  json: async () => JSON.parse("<Error>AccessDenied</Error>"),
};

function assertHidden(link) {
  assert.equal(link.hidden, true);
  assert.equal("href" in link.attrs, false);
}

function assertShown(link, href = HREF) {
  assert.equal(link.hidden, false);
  assert.equal(link.attrs.href, href);
}

test("a session that has not ended gives the dashboard link", () => {
  assert.deepEqual(t.parseLive(live(), NOW), { href: HREF, ends: Date.parse(ENDS) });
});

test("an offset and fractional seconds are accepted in ends", () => {
  assert.ok(t.parseLive(live({ ends: "2026-11-12T16:00:00+05:30" }), NOW - 60 * 60 * 1000));
  assert.ok(t.parseLive(live({ ends: "2026-11-12T11:30:00.250Z" }), NOW));
});

const BAD = {
  null: null,
  "a string": "live",
  "an array": [],
  "schema 2": live({ schema: 2 }),
  "schema as text": live({ schema: "1" }),
  "no url": live({ url: undefined }),
  "http url": live({ url: "http://session.example.test/" }),
  "javascript url": live({ url: "javascript:alert(1)" }),
  "protocol-relative url": live({ url: "//session.example.test/" }),
  "url without a host": live({ url: "https://" }),
  "url with credentials": live({ url: "https://a@session.example.test/" }),
  "url with a backslash": live({ url: "https://session.example.test\\@other.test/" }),
  "url with a newline": live({ url: "https://session.example.test/\n" }),
  "url not a string": live({ url: ["https://session.example.test/"] }),
  "no home": live({ home: undefined }),
  "empty home": live({ home: "" }),
  "relative home": live({ home: "d/cerberus-runs" }),
  "home with two slashes": live({ home: "//other.test/x" }),
  "home with slash backslash": live({ home: "/\\other.test/x" }),
  "home with a later backslash": live({ home: "/d\\x" }),
  "home with a tab": live({ home: "/\t/other.test" }),
  "home with a newline": live({ home: "/\n/other.test" }),
  "home with a space first": live({ home: " /d/x" }),
  "home as a full url": live({ home: "https://other.test/" }),
  "home not a string": live({ home: 1 }),
  "no ends": live({ ends: undefined }),
  "ends in the past": live({ ends: "2026-11-12T10:29:59Z" }),
  "ends now": live({ ends: "2026-11-12T10:30:00Z" }),
  "ends without a zone": live({ ends: "2026-11-12T11:30:00" }),
  "ends as a year": live({ ends: "2099" }),
  "ends as a number": live({ ends: 4102444800000 }),
  "ends that does not exist": live({ ends: "2026-99-99T11:30:00Z" }),
};

for (const [name, data] of Object.entries(BAD)) {
  test(`bad live.json gives no link: ${name}`, () => {
    assert.equal(t.parseLive(data, NOW), null);
  });
}

test("a home that tries to climb stays on the session host", () => {
  const r = t.parseLive(live({ home: "/..//other.test" }), NOW);
  assert.equal(new URL(r.href).host, "session.example.test");
});

test("the link is shown for a future end, read from live.json without a cache", async (tc) => {
  const calls = stubFetch(tc, ok(live()));
  const link = fakeLink();
  await t.watcher(link, () => NOW)();
  assertShown(link);
  assert.equal(calls.length, 1);
  const [url, options] = calls[0];
  assert.equal(url, "live.json");
  assert.equal(options.cache, "no-store");
  assert.ok(options.signal instanceof AbortSignal);
});

const HIDDEN = {
  "a 403 (missing through CloudFront)": missing(403),
  "a 404": missing(404),
  "a 500": missing(500),
  "a 204": missing(204),
  "a body that is not JSON": notJson,
  "a network error": new TypeError("fetch failed"),
  "an http url": ok(live({ url: "http://session.example.test/" })),
  "a past session": ok(live({ ends: "2026-11-12T10:00:00Z" })),
  "a bad home": ok(live({ home: "//other.test" })),
};

for (const [name, answer] of Object.entries(HIDDEN)) {
  test(`the link stays hidden for ${name}`, async (tc) => {
    stubFetch(tc, answer);
    const link = fakeLink();
    await t.watcher(link, () => NOW)();
    assertHidden(link);
  });

  test(`a shown link is hidden again by ${name}`, async (tc) => {
    stubFetch(tc, ok(live()), answer);
    const link = fakeLink();
    const check = t.watcher(link, () => NOW);
    await check();
    assertShown(link);
    await check();
    assertHidden(link);
  });
}

test("the link is hidden when the end time passes", async (tc) => {
  stubFetch(tc, ok(live()));
  const link = fakeLink();
  let now = NOW;
  const check = t.watcher(link, () => now);
  await check();
  assertShown(link);
  now = Date.parse(ENDS);
  await check();
  assertHidden(link);
});

test("an ended session is hidden at once, even if the next read never answers", async (tc) => {
  stubFetch(tc, ok(live()), new Promise(() => {}));
  const link = fakeLink();
  let now = NOW;
  const check = t.watcher(link, () => now);
  await check();
  assertShown(link);
  now = Date.parse(ENDS) + 1;
  check(); // left pending on purpose
  assertHidden(link);
});

test("start checks at once and then every 60 seconds", async (tc) => {
  const calls = stubFetch(tc, ok(live({ ends: "2999-01-01T00:00:00Z" })));
  const link = fakeLink();
  const timers = [];
  const originalInterval = globalThis.setInterval;
  tc.after(() => {
    globalThis.setInterval = originalInterval;
    delete globalThis.document;
  });
  globalThis.setInterval = (fn, ms) => timers.push({ fn, ms });
  globalThis.document = { getElementById: (id) => (id === "live-link" ? link : null) };
  t.start();
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 60 * 1000);
  await timers[0].fn();
  assert.equal(calls.length, 2);
  assertShown(link);
});

test("start does nothing on a page without the link", (tc) => {
  const calls = stubFetch(tc, ok(live()));
  tc.after(() => {
    delete globalThis.document;
  });
  globalThis.document = { getElementById: () => null };
  t.start();
  assert.equal(calls.length, 0);
});

// ---- follow the batch ----

// A very small element: attributes, children, the hidden flag and click events.
// querySelector takes only the "[attribute]" form, which is all site.js uses.
class El {
  constructor(attrs = {}, children = []) {
    this.attrs = { ...attrs };
    this.hidden = "hidden" in attrs;
    this.children = children;
    this.listeners = [];
    this.top = 0;
    this.scrolled = 0;
    this.focused = [];
  }
  getAttribute(name) {
    return name in this.attrs ? this.attrs[name] : null;
  }
  setAttribute(name, value) {
    this.attrs[name] = value;
  }
  addEventListener(type, fn) {
    assert.equal(type, "click");
    this.listeners.push(fn);
  }
  click() {
    assert.equal(this.hidden, false, "a hidden button cannot be pressed");
    for (const fn of this.listeners) fn();
  }
  *walk() {
    for (const child of this.children) {
      yield child;
      yield* child.walk();
    }
  }
  querySelectorAll(selector) {
    const name = /^\[([a-z-]+)\]$/.exec(selector)[1];
    return [...this.walk()].filter((el) => name in el.attrs);
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
  focus(options) {
    this.focused.push(options);
  }
  getBoundingClientRect() {
    return { top: this.top };
  }
  scrollIntoView() {
    this.scrolled += 1;
  }
}

const SIZES = ["1m", "10m", "100m"];
const STATIONS = ["arrive", "clean", "model", "answer"];

// The built page's structure (test_landing_js_scan.py checks it against the HTML).
function fakePage() {
  const picks = SIZES.map(
    (size) =>
      new El({
        "data-pick": "",
        id: `pick-${size}`,
        "aria-controls": `run-${size}`,
        "aria-pressed": size === "100m" ? "true" : "false",
      }),
  );
  const picker = new El({ "data-picker": "", hidden: "" }, picks);
  const runs = SIZES.map((size) => {
    const steps = STATIONS.map(
      (name, i) =>
        new El({
          "data-step": "",
          id: `step-${size}-${name}`,
          "aria-controls": `s-${size}-${name}`,
          "aria-pressed": i === 0 ? "true" : "false",
        }),
    );
    const panels = STATIONS.map(
      (name) =>
        new El({ id: `s-${size}-${name}` }, [
          new El({ "data-next": "", hidden: "", id: `next-${size}-${name}` }),
        ]),
    );
    const stepper = new El({ "data-stepper": "", hidden: "", id: `stepper-${size}` }, steps);
    return new El({ id: `run-${size}` }, [stepper, ...panels]);
  });
  const root = new El({ id: "journey" }, [picker, ...runs]);
  const all = [root, ...root.walk()];
  const byId = (id) => all.find((el) => el.attrs.id === id) ?? null;
  return { getElementById: byId, picker, all };
}

const shownRuns = (doc) => SIZES.filter((s) => !doc.getElementById(`run-${s}`).hidden);
const shownPanels = (doc, size) =>
  STATIONS.filter((n) => !doc.getElementById(`s-${size}-${n}`).hidden);
const pressed = (doc, prefix, names) =>
  names.filter((n) => doc.getElementById(`${prefix}${n}`).attrs["aria-pressed"] === "true");

function assertAt(doc, size, station) {
  assert.deepEqual(shownRuns(doc), [size]);
  assert.deepEqual(pressed(doc, "pick-", SIZES), [size]);
  for (const s of SIZES) {
    // Every run sits at the same station, so another size opens there.
    assert.deepEqual(shownPanels(doc, s), [station]);
    assert.deepEqual(pressed(doc, `step-${s}-`, STATIONS), [station]);
  }
}

test("before the script runs, every run and panel shows and every button is hidden", () => {
  const doc = fakePage();
  assert.deepEqual(shownRuns(doc), SIZES);
  for (const s of SIZES) assert.deepEqual(shownPanels(doc, s), STATIONS);
  assert.equal(doc.picker.hidden, true);
});

test("the script opens the featured run at the first station and shows the buttons", () => {
  const doc = fakePage();
  t.journey(doc);
  assertAt(doc, "100m", "arrive");
  const buttons = doc.all.filter((el) => "data-next" in el.attrs || "data-picker" in el.attrs);
  assert.equal(buttons.length, 13);
  assert.ok(buttons.every((el) => !el.hidden));
  assert.ok(SIZES.every((s) => !doc.getElementById(`stepper-${s}`).hidden));
});

test("the picker changes the run and keeps the station", () => {
  const doc = fakePage();
  t.journey(doc);
  doc.getElementById("step-100m-model").click();
  assertAt(doc, "100m", "model");
  doc.getElementById("pick-1m").click();
  assertAt(doc, "1m", "model");
  doc.getElementById("step-1m-clean").click();
  doc.getElementById("pick-10m").click();
  assertAt(doc, "10m", "clean");
});

test("Next walks the four stations, returns to the first and moves the focus", () => {
  const doc = fakePage();
  t.journey(doc);
  for (const [from, to] of [
    ["arrive", "clean"],
    ["clean", "model"],
    ["model", "answer"],
    ["answer", "arrive"],
  ]) {
    const panel = doc.getElementById(`s-100m-${to}`);
    const before = panel.focused.length;
    doc.getElementById(`next-100m-${from}`).click();
    assertAt(doc, "100m", to);
    assert.deepEqual(panel.focused.slice(before), [{ preventScroll: true }]);
  }
});

test("Next scrolls to the stations only when they left the top of the screen", () => {
  const doc = fakePage();
  t.journey(doc);
  const stepper = doc.getElementById("stepper-100m");
  stepper.top = 120;
  doc.getElementById("next-100m-arrive").click();
  assert.equal(stepper.scrolled, 0);
  stepper.top = -1;
  doc.getElementById("next-100m-clean").click();
  assert.equal(stepper.scrolled, 1);
});

test("a station button does not move the focus", () => {
  const doc = fakePage();
  t.journey(doc);
  doc.getElementById("step-100m-answer").click();
  assert.ok(doc.all.every((el) => el.focused.length === 0));
});

test("a page without the journey is left alone", () => {
  assert.doesNotThrow(() => t.journey({ getElementById: () => null }));
});
