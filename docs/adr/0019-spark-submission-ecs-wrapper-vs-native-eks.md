# 19. Spark job submission: keep the ECS wrapper, with stated triggers to replace it

Date: 2026-10-10

## Status

Proposed

## Context

Since 4.2, the state machine's `RunTransform` step starts a short-lived ECS
Fargate task (`ecs:runTask.sync`). The task runs
`orchestration/runner/entrypoint_transform.sh`, which uploads the Spark
script to S3, writes a kubeconfig, deletes the previous `SparkApplication`,
fills in the OpenLineage URL, `kubectl apply`s the manifest, polls its state
every 5 seconds for up to 20 minutes, and prints the driver log if the job
fails. The Spark job itself runs on the `dev-compute` EKS cluster through the
Spark Operator.

8.6 measured what that wrapper costs. On every run the Fargate task takes
about 25 seconds to start (task creation to the first log line) and about 25
seconds to stop (the last log line to the end of the state). Measured from the
execution histories and the task logs:

| Run | Events | RunTransform | Wrapper (start + stop) | Share |
|---|---|---|---|---|
| `exercise-20261008T160759Z` | 1M silver, 6k new | 178.3 s | 25.6 + 24.4 = 50.0 s | 28% |
| `exercise-20261009T062108Z` (image pre-pull, #76) | 1M silver, 6k new | 159.0 s | 25.1 + 25.1 = 50.2 s | 32% |
| `exercise-20261009T074853Z` (10M, 1 × 1 GB) | 9.0M new | 323.3 s | 24.3 + 25.2 = 49.5 s | 15% |
| `exercise-20261009T101830Z` (10M, 2 × 2 GB) | 9.0M new | 241.6 s | 30.2 + 25.8 = 56.0 s | 23% |

The wrapper costs a fixed ~50 seconds, so its share falls as the data
grows. `RunDbt` pays the same Fargate start, but this ADR is only about
the Spark submission.

The alternative is Step Functions' optimized Amazon EKS integration, which
talks to the cluster's Kubernetes API directly. Checked against the Step
Functions developer guide on 2026-10-10:

- **`eks:runJob(.sync)`** runs only `batch/v1` Jobs, and its `.sync` pattern
  polls at about one poll per minute, slowing to one every five minutes. For
  a job of a few minutes, that polling alone can add more than the wrapper
  costs. A `SparkApplication` is a custom resource, so it needs
  **`eks:call`**, a plain Kubernetes REST call with no `.sync` pattern: the
  state machine has to build its own poll loop (`Wait` + `eks:call GET` +
  `Choice`).
- Every EKS call needs the cluster's `Endpoint` and `CertificateAuthority`.
  `dev-compute` is created again for each exercise, so both change on every
  apply, while the state machine lives in `dev-standing` (ADR 0011). The
  state machine would have to look them up at run time (an
  `aws-sdk:eks:describeCluster` state).
- The integration **supports only API servers with public endpoint access.**
  The cluster's endpoint is public today
  (`endpoint_public_access = true`), but ADR 0016 recorded private endpoint
  access as a follow-up. The ECS task runs inside the VPC and works with a
  private endpoint.
- A task's input or result is capped at 256 KiB, so driver logs could only
  come back as a tail (`tailLines`).

**Forces, by pillar:**

- **Performance Efficiency (the case for changing).** About 50 seconds per
  run, 15–32% of `RunTransform` at today's volumes. That is real, but it
  is fixed, and the data work grows: at the 100M step the job is expected
  to run for many minutes, and 50 seconds becomes a few percent.
- **Reliability.** The wrapper's logic is ordinary, tested Bash: delete
  before submit makes a retry safe (4.3), and the poll loop is bounded. In
  `eks:call` form the same logic becomes five to seven states (describe
  cluster, delete with a 404 catch, create, wait, get, choice, a counter or
  timeout), each with its own retry and error handling, in Amazon States
  Language that can only be tested one state at a time (the TestState API)
  or with a live cluster.
- **Security.** The wrapper reaches the cluster from inside the VPC through
  an EKS access entry and a namespaced RBAC role (`spark_job` module). The
  native integration needs the same RBAC for the state machine's role, but
  also ties the platform to a public API server endpoint, closing off ADR
  0016's private-endpoint follow-up for as long as it is used.
- **Cost Optimization.** Roughly neutral. The Fargate task costs well under
  a cent per run; an `eks:call` poll loop costs a few hundred state
  transitions on the 100M step, also well under a cent. Neither moves the
  $20/month budget.
- **Operational Excellence.** The wrapper's output is one CloudWatch log
  stream per run that reads top to bottom. The native version spreads the
  same story across execution-history events, with logs truncated to fit
  256 KiB. `exercise.sh` saves the full Spark logs either way (#74), but
  the scheduled path does not use `exercise.sh`.
- **Sustainability.** Not decisive: the Fargate task is a small, short
  container.

**The SLO view.** SLO 3 targets a full run in under 30 minutes. The four
runs above took 5.6 to 10.4 minutes end to end. The wrapper's 50 seconds
puts no SLO at risk today.

## Decision

**Keep the ECS Fargate wrapper for submitting and watching the Spark job.**
Do not move `RunTransform` to the native EKS integration in Phase 8.

Revisit this ADR, with the `eks:call` design below as the ready alternative,
when any of these becomes true:

1. **Latency pressure:** the run latency SLO (SLO 3) is at risk, or a
   tighter latency target is set, and the wrapper's ~50 seconds is a
   meaningful part of the gap.
2. **The data stops growing:** the wrapper's share of `RunTransform` stays
   above 25% at the platform's steady-state volume (after the scale ladder).
3. **Frequency:** the pipeline runs much more often than daily (for example
   micro-batches after Phase 12's streaming ingestion), so the fixed cost is
   paid many times an hour.
4. **The wrapper itself becomes the problem:** the runner image or
   `entrypoint_transform.sh` turns into a maintenance burden for reasons
   other than latency.

Trigger 3 is the most likely one. The public-endpoint requirement has to be
weighed again whenever a trigger fires.

**The ready alternative (not built):**

1. `aws-sdk:eks:describeCluster` → `Endpoint` and `CertificateAuthority`
   into the state's data; the state machine role gets
   `eks:DescribeCluster` on the cluster's fixed name.
2. `eks:call DELETE` the previous `SparkApplication`, with a `Catch` for
   `EKS.404`.
3. `eks:call POST` the manifest, rendered by Terraform with the OpenLineage
   URL already in it.
4. A poll loop: `Wait` 10 s → `eks:call GET` → `Choice` on
   `status.applicationState.state` (`COMPLETED` → next; `FAILED` → fetch the
   driver log tail with `eks:call GET .../pods/<driver>/log?tailLines=200`
   and fail; else loop), bounded by the step's `TimeoutSeconds`.
5. The Spark script moves from the runner image to an `aws_s3_object` in
   `dev-standing` (CI-applied), so a script change no longer needs a local
   image rebuild.
6. An EKS access entry and RBAC role for the state machine's role, in the
   `spark_job` module, with the same verbs the wrapper's role has today.

## Consequences

- **Accepted cost:** about 50 seconds per run stays in `RunTransform`,
  15–32% of the step at today's volumes and shrinking with scale.
- **Kept:** the private-endpoint option from ADR 0016, a submission path
  that is plain Bash with one readable log stream per run, and the existing
  retry semantics.
- **Still true, separately:** any change to `transform/spark/` files baked
  into the runner image still needs a local `make standing-apply` before
  merge (`build_and_push`). Step 5 of the alternative would remove that,
  and it could be done on its own.
- **Measured, not assumed:** this decision rests on four timed runs. The
  100M run (8.9) records the same breakdown, and that is the first check
  of whether trigger 2 can fire.
- **The 8.6 latency work that did land:** the Spark image pre-pull (#76,
  −19 s per run) and two 2 GB executors (#77, −25% of `RunTransform` at
  10M).
