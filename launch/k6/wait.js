// Pure arithmetic for download.js (no k6 imports, so node can test it).

// Whole seconds from nowMs until releaseAtEpoch (epoch seconds); 0 when past.
// The wait is a sleep, not a poll: waiting sends no request, so it adds no
// request count and no 403 (ADR 0030 Decision 13 compares counts with logs).
export function secondsUntil(releaseAtEpoch, nowMs) {
  return Math.max(0, Math.ceil(releaseAtEpoch - nowMs / 1000));
}

// k6 stops setup() after setupTimeout (60 s by default). The setup of a gated
// run sleeps until T0 and then asks for the licence up to `tries` times,
// `stepSeconds` apart, so the timeout covers all of it plus a minute.
export function setupTimeoutSeconds(sleepSeconds, tries, stepSeconds) {
  return sleepSeconds + tries * stepSeconds + 60;
}

// Start offset in whole seconds of client i of a ramp (run B): the clients are
// spread evenly over rampMinutes, the first one at 0.
export function startSeconds(i, clients, rampMinutes) {
  return Math.round((rampMinutes * 60 * i) / clients);
}

// Chunk requests per client: the set's chunk count, or `chunks` when it is smaller.
export function chunkCount(setChunks, limit) {
  return limit ? Math.min(setChunks, limit) : setChunks;
}
