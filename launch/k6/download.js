// Launch download scenario (ADR 0030). One script for every run: the scenario
// JSON (launch/scenarios/<name>.json, run RUN_INDEX) sets the workloads, and
// sets.json holds the object sets. Fixed iterations only: per-vu-iterations and
// shared-iterations, so requests and bytes are counted, never timed.
// maxDuration below is k6's stop cap on the same executors, not a load shape.
//
// Chunks are content-addressed (<prefix>/<sha256>.bin). Their names are in a
// manifest: the instance reads its local copy (MANIFEST_DIR/<set>.json, made by
// launch/seed.py); probe P (manifest_from_edge) reads it through the signed edge.
//
// Environment (-e): SCENARIO_FILE, SETS_FILE, COOKIE_FILE, EDGE_DOMAIN, MINUTES,
// RUN_INDEX (default 0), MANIFEST_DIR (not for manifest_from_edge), RELEASE_AT
// (epoch seconds; for a gated run or a wait:release step). EDGE_SCHEME is for
// the tests only: http is accepted for 127.0.0.1 or localhost and nothing else.
// The cookie header is read from a file (open) and is never logged.
import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { secondsUntil, setupTimeoutSeconds, startSeconds, chunkCount } from './wait.js';

const spec = JSON.parse(open(__ENV.SCENARIO_FILE));
const sets = JSON.parse(open(__ENV.SETS_FILE));
const run = spec.runs[Number(__ENV.RUN_INDEX || 0)];
if (!run) throw new Error('RUN_INDEX is not a run of this scenario');
const cookie = open(__ENV.COOKIE_FILE).trim();
const domain = __ENV.EDGE_DOMAIN;
const scheme = __ENV.EDGE_SCHEME || 'https';
if (scheme !== 'https' && !(scheme === 'http' && /^(127\.0\.0\.1|localhost)(:\d+)?$/.test(domain))) {
  throw new Error('EDGE_SCHEME must be https (http only for a local test server)');
}
const base = `${scheme}://${domain}`;
const GATE_TRIES = 30; // licence requests after T0 before the run gives up
const GATE_STEP_SECONDS = 2;
const maxDuration = `${__ENV.MINUTES}m`;

// Request and byte counters by type, for the run record (k6_requests) and the
// comparison with the CDN logs. http_reqs counts every request; these split it.
const req = {
  build: new Counter('req_build'),
  patch: new Counter('req_patch'),
  licence: new Counter('req_licence'),
  manifest: new Counter('req_manifest'),
};
const bytes = {
  build: new Counter('bytes_build'),
  patch: new Counter('bytes_patch'),
  licence: new Counter('bytes_licence'),
};
const licenceRetry = new Counter('licence_retry'); // extra licence requests after a 403 that should be 200
const licenceDenied = new Counter('licence_denied'); // a flood request that was not 200
const licenceUnexpected = new Counter('licence_unexpected'); // a before-release 403 that was 200
const chunkErrors = new Counter('chunk_errors'); // status not 200, or length not the manifest's

const hasWait = run.workloads.some((w) => (w.steps || []).includes('wait:release'));
const gated = run.gate === 'release';
const needsRelease = gated || hasWait;
const releaseAt = Number(__ENV.RELEASE_AT);
if (needsRelease && !Number.isFinite(releaseAt)) {
  throw new Error('RELEASE_AT is required for a run that waits for the release');
}

function setsOf(w) {
  if (w.kind === 'fetch') return [w.set];
  if (w.kind === 'sequence') return w.steps.filter((s) => s.startsWith('fetch:')).map((s) => s.slice(6));
  return [];
}
const edgeManifest = run.workloads.some((w) => w.manifest_from_edge);

// Local manifests (the instance): the chunk count must be the plan's.
const local = {};
if (!edgeManifest) {
  for (const name of new Set(run.workloads.flatMap(setsOf))) {
    const m = JSON.parse(open(`${__ENV.MANIFEST_DIR}/${name}.json`));
    if (m.chunks.length !== sets.sets[name].chunks) {
      throw new Error(`manifest ${name} has ${m.chunks.length} chunks, the plan has ${sets.sets[name].chunks}`);
    }
    local[name] = m;
  }
}

// k6 scenario name -> workload; one k6 scenario per client when ramped.
const conf = {};
const scenarios = {};
for (const w of run.workloads) {
  if (w.kind === 'fetch') {
    const iterations = chunkCount(sets.sets[w.set].chunks, w.chunks);
    if (w.ramp_minutes) {
      for (let i = 0; i < w.clients; i++) {
        const name = `${w.name}-${i}`;
        conf[name] = w;
        scenarios[name] = {
          executor: 'per-vu-iterations', exec: 'fetchSet', vus: 1, iterations, maxDuration,
          startTime: `${startSeconds(i, w.clients, w.ramp_minutes)}s`,
        };
      }
    } else {
      conf[w.name] = w;
      scenarios[w.name] = {
        executor: 'per-vu-iterations', exec: 'fetchSet', vus: w.clients, iterations, maxDuration,
      };
    }
  } else if (w.kind === 'licence') {
    conf[w.name] = w;
    scenarios[w.name] = {
      executor: 'shared-iterations', exec: 'licenceFlood', vus: w.vus, iterations: w.total, maxDuration,
    };
  } else if (w.kind === 'sequence') {
    conf[w.name] = w;
    scenarios[w.name] = {
      executor: 'per-vu-iterations', exec: 'sequence', vus: 1, iterations: 1, maxDuration,
    };
  } else {
    throw new Error(`unknown workload kind ${w.kind}`);
  }
}

const sleepFirst = gated ? secondsUntil(releaseAt, Date.now()) : 0;

export const options = {
  // Per-client DNS, spread over every returned address (AWS load-testing page).
  dns: { ttl: '0', select: 'random' },
  // p(50) and p(99) are for the TTFB comparison with the CDN logs.
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(90)', 'p(95)', 'p(99)'],
  scenarios,
  ...(gated ? { setupTimeout: `${setupTimeoutSeconds(sleepFirst, GATE_TRIES, GATE_STEP_SECONDS)}s` } : {}),
};

function get(path, type, text) {
  const params = { headers: { Cookie: cookie }, tags: { type }, ...(text ? {} : { responseType: 'none' }) };
  const res = http.get(`${base}${path}`, params);
  req[type].add(1);
  return res;
}

function licence() {
  const res = get('/license', 'licence', true);
  bytes.licence.add((res.body || '').length); // 200 and 403 bodies are in the plan
  return res;
}

// One licence request that must answer 200, retried a bounded number of times.
function licence200() {
  for (let i = 0; i < GATE_TRIES; i++) {
    const res = licence();
    if (res.status === 200) return true;
    licenceRetry.add(1);
    sleep(GATE_STEP_SECONDS);
  }
  return false;
}

function chunk(type, entry) {
  const res = get(`/${entry.key}`, type, false);
  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'length is the manifest length': (r) => Number(r.headers['Content-Length']) === entry.bytes,
  });
  if (ok) bytes[type].add(entry.bytes);
  else chunkErrors.add(1);
}

// setup: sleep until T0 (no request), ask for the licence, and, for probe P,
// read the manifest through the edge. No retry on a 403 other than the licence.
export function setup() {
  const data = { manifests: {} };
  if (gated) {
    sleep(sleepFirst);
    if (!licence200()) throw new Error('the licence did not answer 200 after the release');
  }
  if (edgeManifest) {
    for (const name of new Set(run.workloads.flatMap(setsOf))) {
      const res = get(`/${sets.sets[name].manifest}`, 'manifest', true);
      if (res.status !== 200) throw new Error(`manifest ${name} answered ${res.status}`);
      data.manifests[name] = JSON.parse(res.body);
      if (data.manifests[name].chunks.length !== sets.sets[name].chunks) {
        throw new Error(`manifest ${name} has the wrong chunk count`);
      }
    }
  }
  return data;
}

function manifestOf(name, data) {
  return edgeManifest ? data.manifests[name] : local[name];
}

// Each client downloads the chunks of the set in order, one per iteration.
export function fetchSet(data) {
  const w = conf[exec.scenario.name];
  const m = manifestOf(w.set, data);
  chunk(sets.sets[w.set].prefix, m.chunks[exec.vu.iterationInScenario]);
}

// Licence flood: a fixed number of requests, paced so vus / pace is the rate cap.
export function licenceFlood() {
  const w = conf[exec.scenario.name];
  const res = licence();
  if (res.status !== 200) licenceDenied.add(1);
  sleep(w.vus / w.rate_cap_per_s);
}

// Run A: one client does the steps in order. licence:403 asks once before the
// release; wait:release sleeps (no polling); licence:200 asks after it.
export function sequence(data) {
  const w = conf[exec.scenario.name];
  for (const step of w.steps) {
    if (step.startsWith('fetch:')) {
      const name = step.slice(6);
      const m = manifestOf(name, data);
      for (const entry of m.chunks) chunk(sets.sets[name].prefix, entry);
    } else if (step === 'licence:403') {
      const res = licence();
      if (res.status !== 403) licenceUnexpected.add(1);
    } else if (step === 'wait:release') {
      sleep(secondsUntil(releaseAt, Date.now()) + 1);
    } else if (step === 'licence:200') {
      if (!licence200()) throw new Error('the licence did not answer 200 after the release');
    }
  }
}
