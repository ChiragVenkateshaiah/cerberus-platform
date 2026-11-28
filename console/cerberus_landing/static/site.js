"use strict";
// The landing page's only script (plan docs/plans/2026-11-28-landing-showcase.md).
// It does two things.
// 1. "Follow the batch": every run and station is already in the page. This shows
//    the buttons and hides all but the chosen run and station. It writes no text.
// 2. The link to the live Grafana dashboard while a session runs. envs/dev-console
//    writes live.json at the site root and deletes it first on destroy. After a
//    dead trap the file stays, so `ends` is the only guard (console/README.md).
//    The checks follow cerberus_live_check/report.py parse_live.

const READ_TIMEOUT_MS = 10000; // shorter than CHECK_MS: reads never overlap
const LIVE_PATH = "live.json";
const CHECK_MS = 60 * 1000;
// RFC 3339 with a zone: Date.parse alone also accepts strings such as "2099".
const ENDS_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
// Printable ASCII with no space and no backslash: a browser drops tabs and
// newlines from a URL and reads "\" as "/", so "/\host" would leave the site.
const URL_RE = /^https:\/\/[\x21-\x5b\x5d-\x7e]+$/;
const HOME_RE = /^\/(?!\/)[\x21-\x5b\x5d-\x7e]*$/;

// {href, ends} for a session that runs at `now` (ms), otherwise null.
function parseLive(data, now) {
  if (data === null || typeof data !== "object" || data.schema !== 1) return null;
  if (typeof data.url !== "string" || !URL_RE.test(data.url)) return null;
  if (typeof data.home !== "string" || !HOME_RE.test(data.home)) return null;
  if (typeof data.ends !== "string" || !ENDS_RE.test(data.ends)) return null;
  const ends = Date.parse(data.ends);
  if (!(ends > now)) return null; // also false for a date that does not parse
  try {
    const base = new URL(data.url);
    const target = new URL(data.home, base);
    if (base.username || base.password || target.origin !== base.origin) return null;
    return { href: target.href, ends: ends };
  } catch {
    return null;
  }
}

// The parsed file, or null: any status but 200 (a missing file is 403 through
// CloudFront), a network error and a body that is not JSON all mean "no session".
async function readLive() {
  try {
    const res = await fetch(LIVE_PATH, {
      cache: "no-store",
      signal: AbortSignal.timeout(READ_TIMEOUT_MS),
    });
    return res.status === 200 ? await res.json() : null;
  } catch {
    return null;
  }
}

// A hidden link has no href, so it can never be followed.
function show(link, live) {
  if (live) {
    link.setAttribute("href", live.href);
    link.hidden = false;
  } else {
    link.hidden = true;
    link.removeAttribute("href");
  }
}

// One check of live.json for this link; `now` returns the time in ms.
function watcher(link, now) {
  let ends = 0;
  return async function check() {
    // Hide an ended session at once, even if the next read hangs.
    if (!(ends > now())) show(link, null);
    const data = await readLive();
    const live = parseLive(data, now());
    ends = live ? live.ends : 0;
    show(link, live);
  };
}

// Marks one button of a set as chosen and shows only the element it controls.
function choose(doc, buttons, index) {
  buttons.forEach((button, i) => {
    button.setAttribute("aria-pressed", i === index ? "true" : "false");
    doc.getElementById(button.getAttribute("aria-controls")).hidden = i !== index;
  });
}

// The run buttons pick a run. The station buttons and "Next" pick a station, in
// every run at once, so another run opens at the same station.
function journey(doc) {
  const root = doc.getElementById("journey");
  if (!root) return;
  const picks = Array.from(root.querySelectorAll("[data-pick]"));
  const steppers = Array.from(root.querySelectorAll("[data-stepper]"));
  const rows = steppers.map((stepper) => Array.from(stepper.querySelectorAll("[data-step]")));
  const station = (index) => rows.forEach((steps) => choose(doc, steps, index));

  picks.forEach((button, i) => button.addEventListener("click", () => choose(doc, picks, i)));
  rows.forEach((steps, row) => {
    steps.forEach((step, i) => {
      step.addEventListener("click", () => station(i));
      const panel = doc.getElementById(step.getAttribute("aria-controls"));
      const next = panel.querySelector("[data-next]");
      next.addEventListener("click", () => {
        const to = (i + 1) % steps.length;
        station(to);
        // The button just pressed is now hidden: move the focus to the new panel,
        // and bring the stations back into view if they scrolled off the top.
        const shown = doc.getElementById(steps[to].getAttribute("aria-controls"));
        shown.focus({ preventScroll: true });
        if (steppers[row].getBoundingClientRect().top < 0) steppers[row].scrollIntoView();
      });
      next.hidden = false;
    });
    steppers[row].hidden = false;
  });

  station(0);
  // The page marks the featured run's button as the chosen one.
  choose(doc, picks, picks.findIndex((b) => b.getAttribute("aria-pressed") === "true"));
  root.querySelector("[data-picker]").hidden = false;
}

function start() {
  journey(document);
  const link = document.getElementById("live-link");
  if (!link) return;
  const check = watcher(link, Date.now);
  check();
  setInterval(check, CHECK_MS);
}

if (typeof document !== "undefined") {
  start();
}
if (typeof module !== "undefined") {
  module.exports = { CHECK_MS, LIVE_PATH, parseLive, watcher, journey, start };
}
