# Plan: 17.2 downloads generator

Date: 2026-11-25. Planner: Sonnet.

**1. Goal.** Phases.md 17.2: a deterministic `downloads` generator, its SparkApplication YAML, unit tests, and a 10k-event sample. No NEEDS DECISION. ADR 0030 Decisions 7, 8 and 10 cover it, and ADR 0018 is amended only for the prefix.

**2. Facts** (V = verified in the repo)
- (V) `verify.sh` and `code-ci.yml` run no Spark tests. Nothing installs pyspark; `requirements-dev.txt` has no pyspark. CI has a py3.10 job (spark_progress), and the cluster image runs py3.10.
- (V) `generate_bulk_payments.py` is one file, uploaded alone. It hardcodes the account ID, and `verify_scan.py` flags any 12-digit run in added or untracked text files (binary files are skipped).
- (V) Payments pattern: hash-derived randomness, `--now` argument, dynamic partition overwrite, `repartition(dt, _bucket)`, manifest written last.
- (V) ADR 0030 Decision 7: UUIDv7 layout with a 48-bit ms timestamp and 74 hash bits. `ingested_at` is the `--now` argument.
- (V) Launch plan section 4 sets the payload, event types, window and shape. Section 7 sets the cut lines: the curve fallback, then 10M events.
- (U) Throughput at 100M for a Python-core job on dev-compute.
- (U) Whether the image has pyarrow (assume not).

**3. Decisions and spec**

*Pure-Python core vs Spark expressions.*
- Use a pure-Python core inside `transform/spark/generate_bulk_downloads.py`.
- Import pyspark lazily inside `main()`, so tests need no Spark.
- Spark only distributes clients: `spark.range(clients).rdd.mapPartitions(...)`. Test and production run the same code.
- Do not use `mapInPandas`, because pyarrow is not verified.
- Keep it as one file with no `pyFiles`, matching the payments job.
- Keep the Spark code under about 80 lines.

*Hash scheme.*
- `u(run_id, client_id, salt)` is SHA-256 of `"|".join(...)`, taken as the top 53 bits divided by 2^53. Reject a `|` in `run_id`.
- `event_id` is SHA-256 of `f"{run_id}|{client_id}|{event_type}|{sequence}"`. Sequence is the 0-based index in the client's time-ordered events.
- Layout: 48-bit `occurred_at` ms, then `0111`, then the top 12 hash bits, then `10`, then the next 62 bits.
- Format the result as 8-4-4-4-12 hex.
- Enforce strictly increasing ms per client, so the order is stable.

*Client timeline.* The window is 2026-11-10T00:00Z to 2026-11-22T00:00Z. This gives 12 `dt` values.
- **Regions and ISPs:** `region_01..24` map to UTC offsets -11..+12. Each region has 2 ISPs, `isp_<nn>_<a|b>`, 48 in all, with a 60/40 share by hash.
- **Pre-load roll:** p=0.46.
- **Pre-load start:** inverse-CDF over hourly bins per region, with a cached cumulative list and `bisect`.
  - An opening-spike term decays from day 0.
  - A diurnal term uses local hours 18-23.
  - An extra final-evening bump falls on the local evening of 11-18.
- **Release:** 2026-11-19T00:00 local, which is `00:00Z` minus the offset.
- **Pre-loaders:** `license_requested` at release plus 0-5 min of jitter. About 3% ask early and get `http_status` 403, then a `retried` event. `license_granted` is never before release.
- **Non-pre-loaders:** start the full download at release plus an exponential delay.
- **Everyone:** gets the 0.5 GB patch (`patch_started`, `patch_completed`) before `install_completed`.
- **Abandon:** about 3% end in a terminal `abandoned`.
- **Window end:** drop events at or after the end. Time order makes this a suffix cut, so the lifecycle stays valid.
- **`--now`:** must be at or after the window end, so `occurred_at` <= `ingested_at`.

*Event count.*
- Title: 212 GB divided by 5 GB chunks gives 42.4, so 43 `chunk_completed` events (the last is 2 GB).
- Add `preload_started`, `preload_completed`, `license_requested`, `license_granted`, 2 patch events and `install_completed`. That is about 50 plus stalls and retries.
- 2M clients x 50 is 100M, which matches the target.
- `EVENTS_PER_CLIENT = 50`, and `clients = ceil(events/50)`. A test asserts the sample mean is within 48-54. The manifest records the actual `events` and `clients`; the target is about +/-2%.
- A `--clients` override is optional.

*Congestion.*
- **Pass 1** uses a nominal plan per client: the ISP, the start minute and the nominal minutes. Emit +1 at the start and -1 at the end, then use `rdd.treeAggregate` with per-ISP `array('i')`.
  - The driver gets about 48 x 17,280 x 4 B = 3.3 MB. It does not `collect` tuples, because the driver has 1 GB.
  - Take a cumsum to get active clients per (isp, minute), and broadcast it.
- **Capacity:** capacity = headroom x peak nominal demand, so it scales with `--events`. Headroom is 1.25. One fixed ISP is under-provisioned at 0.55.
  - After that ISP exceeds 1.0 utilisation, a "traffic management" cap of 50 Mbps applies for 180 min.
- **Pass 2** regenerates the plan and applies throughput = min(nominal, capacity share). It raises stall probability with utilisation.
- **Limit:** the active counts use nominal, not stretched, durations. There is no feedback loop.
- **Curve fallback:** `--congestion curve` takes active counts from a closed-form curve, with no pass 1.
- **Survives 100M:**
  - Cheap pass 1.
  - Streaming generators with no per-client lists in the driver.
  - `repartition(dt, _bucket)` as in payments.
  - `files_per_dt` is about 30 (100M x 450 B / 12 / 128 MB).
  - `memoryOverhead` is about 1g for the Python workers (unverified).

*Lifecycle invariants.* They hold by construction, and `validate_lifecycle(events)` checks them.
- No `install_completed` without a prior `license_granted`.
- No `license_granted` before local release.
- Each event's `bytes` is at most 212e9. Per-client chunk bytes sum to at most the title, and exactly the title unless abandoned. `stalled` and `retried` carry 0 or partial bytes.
- Install comes after the patch.
- Nothing follows `abandoned`.
- Timestamps fall inside the window.
- Use `212 * 10**9` in code, not a 12-digit literal.

*Manifest.*
- Delete any old `_manifest.json` before writing, so a re-run is not marked complete.
- Count by reading back the written output with `groupBy(dt)`, not by regenerating. This avoids doubling the Python cost.
- Write the manifest last, from the Hadoop FS, copied from payments.
- Fields: `run_id`, `now`, `events`, `clients`, `congestion`, `per_dt{events,objects,bytes}`, `source`.

*Names.* All synthetic: `region_nn`, `isp_nn_a`, `isp_nn_b`, `plat` ps5|xbox, `client_id` `cl_<hex>`.

*CLI ARGs.*
- `--run-id` (required)
- `--events` (required)
- `--now` (required)
- `--congestion {two-pass,curve}` (default two-pass)
- `--clients` (optional)
- `--target-file-mb` (default 128)
- `--output` (required, no bucket default, so no account ID in the file)
- `--local PATH` (pure-Python run with no Spark; used for the sample and tests)

**4. Steps** (one PR)
1. Create `transform/spark/generate_bulk_downloads.py` with the core, the Spark `main()` and local mode.
2. Create `transform/spark/spark-application-generate-downloads.yaml`.
   - Copy the payments YAML, with name `cerberus-generate-bulk-downloads`.
   - Placeholders: `__RUN_ID__`, `__EVENTS__`, `__NOW__`, `__EXECUTORS__`, `__CONGESTION__`, `__OUTPUT__`, `__SILVER_BUCKET__`.
   - No account ID. The 17.5 `launch_exercise.sh` fills the placeholders.
3. Create `transform/spark/tests/test_generate_bulk_downloads.py`, with `sys.path` set in a `conftest.py`.
4. Create `data/samples/downloads/sample_10k.jsonl.gz` and a short `README.md`.
   - Generate it with `--local --events 10000`, using `GzipFile(mtime=0)`.
   - A test regenerates it and compares the decompressed content (golden file).
5. In `orchestration/verify.sh`, add `uv run --no-project --python 3.10 --with pytest==9.1.1 python -m pytest -q transform/spark/tests`. In `code-ci.yml`, add a pytest step to the py3.10 job.

**Acceptance tests**
- Determinism: same args give identical output. A different `run_id` gives different IDs and the same count.
- UUIDv7: version nibble 7, variant bits `10`, the timestamp prefix equals `occurred_at`, and IDs are unique on the sample.
- Lifecycle validator: it passes on all sample clients, and it fails on hand-made bad streams (one for each invariant).
- Local release: no licence is granted before local release in any of the 24 regions.
- Shape: the first-6h spike holds more than 1.5x the average pre-load hour. The share of clients that pre-load is within 0.46 +/- 0.03 (use a client-only test at 20k clients). The 11-18 evening peak is present.
- Congestion: with a 3k-client single-ISP fixture, release-window throughput is lower than off-peak and the traffic-management cap applies. The curve mode runs.
- Window and `--now`: no event is outside the window, and `--now` earlier than the window end is rejected.
- Events per client: sample mean within 48-54.
- Sample size: under 1.5 MB.
- No account ID, and no real ISP or platform names, in any output.

**5. Verify.** `make verify` (the new py3.10 check is included). `make verify-full` is not needed.

**6. Owner steps.** None for 17.2. The Friday smoke (`--events 1000000`, then 10M) runs through the 17.5 wrapper. It is the first Spark proof, so run it before the 100M run.

**7. Risks**
- The Spark path is not covered in CI. Keep that code small and run the owner smoke test.
- Python-core throughput at 100M is unverified. A rough estimate is about 1 ms per client, so about 2000 core-seconds, or about 7 min on 8 executors.
- `verify_scan.py` would flag a plain-text sample, because about 0.4% of UUIDs have an all-digit last group and `bytes` can reach 12 digits. The gzip file is not scanned. Do not add a scan exemption.
- `rdd.toDF` serialisation overhead and Python-worker memory are unverified.

**Open questions.** Sample as gz or plain? Recommend gz (about 0.5-1.5 MB, versus about 4.5 MB plain). Otherwise none.

## Main-session corrections (they win)

- Platform values are `console_a` and `console_b`, in the field `platform`
  (ADR 0030 Decision 1: synthetic names only; the launch plan's `ps5|xbox`
  are real product names).
- Clients that do not pre-load emit no `preload_*` event; their full download
  is `chunk_completed` events. The 46% share is measured from `preload_started`.
- The sample is gzip, as recommended.
