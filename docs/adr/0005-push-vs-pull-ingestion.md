# 5. Event-driven ingestion: push (S3 event notification) vs. pull (EventBridge Scheduler)

Date: 2026-08-11

## Status

Proposed

## Context

Phase 2's goal ([plan.md](../plan.md#phase-2--event-driven-ingestion)) is to
replace `cerberus-payments.timer` — a **1.3 artifact**, not the actual Phase
0 timer (`cerberus-ingest.timer`, weather, already retired 2026-08-07) —
with something that doesn't depend on a logged-in session on one machine.
This is not a theoretical gap: systemd linger is off for this user, and the
timer's own history already shows it. `Persistent=true` means missed runs
catch up rather than vanish, but the actual run timestamps in
`payments/dt=*/` show it skipped 2026-08-09 entirely and ran late on
2026-08-10 (01:12, not 00:00) and 2026-08-11 (04:09) — the schedule is
already degrading, observably, not hypothetically. plan.md's stack line
names the options rather than picking one: "Lambda triggered by S3 events /
EventBridge." This ADR makes that choice before 2.1–2.3 build against it,
per this project's established pattern of an ADR before the code it governs
(0002 before 1.4, 0003 before 1.3).

The two concrete mechanisms on the table, named specifically rather than as
a general "scheduled vs. event" abstraction:

- **EventBridge Scheduler** — a managed schedule (cron or rate expression,
  with native timezone support) invokes the Lambda directly. Pull-shaped:
  the same "run on a timer" model `cerberus-payments.timer` already uses,
  relocated onto managed infrastructure. Chosen over the older
  CloudWatch-Events-style scheduled rule specifically because AWS's current
  guidance for new scheduled workloads is Scheduler, and its native retry
  policy + dead-letter queue + flexible time window are direct answers to
  the reliability gap above — a legacy rule offers none of those.
- **S3 event notification** — an `ObjectCreated` event on the bronze bucket
  invokes the Lambda. Push-shaped: fires the instant an object lands,
  triggered by *someone else's* write.

Step Functions and an SQS buffer in front of the Lambda were both
considered and set aside without a full pillar workup: Step Functions is
Phase 4's tool for orchestrating a multi-step pipeline, not a single daily
invocation; SQS solves for decoupling and backpressure this project doesn't
have (one producer, one consumer, low volume) — both are complexity ahead
of the actual need at this phase.

Working the real options through the Well-Architected pillars (per the
method in checkpoint.md's reference section):

| Pillar | What it asks of this decision |
|---|---|
| **Cost Optimization** | Priced both mechanisms against this project's actual measured data rate (~283 KB / 8 S3 `PutObject` calls per daily `count=200` run) rather than guessing: Lambda, EventBridge Scheduler, and S3 PUT/storage costs all land inside their perpetual free tiers at this volume — running the schedule for 10 days costs about $0.0004, for 30 days about $0.0014, versus the existing $10/month billing alarm. Genuinely not decisive between the two mechanisms (S3 notifications would be equally free here) — but decisive against letting cost drive any part of this decision, including the retirement-window question below. |
| **Reliability** | EventBridge Scheduler's native retry policy and flexible time window are a real answer to the catch-up/delay behavior already observed above. But retry cuts both ways here — see the Consequences section: at-least-once delivery against an intentionally unseeded generator is a new risk this decision introduces, not a pure win. An S3 event notification has no independent schedule to be reliable *about*; its reliability question is entirely "did the write that triggers it happen," which is circular for a self-producing function (see the tension below). |
| **Operational Excellence** | A schedule maps 1:1 onto what it's replacing — a human debugging "why did ingestion run" looks for a schedule, exactly like today's timer, and can invoke the Lambda on demand the same way `generate_payments.py` is already run by hand. An S3 event trigger on a function that *is* the producer of the object that would trigger it is backwards to reason about. |
| **Security** | Roughly neutral, on closer inspection — both mechanisms need exactly one `aws_lambda_permission` granting the trigger service `lambda:InvokeFunction`, scoped by a source-ARN condition (EventBridge Scheduler additionally needs its own execution role trusted by `scheduler.amazonaws.com`, which is a comparable, not smaller, footprint than S3 notification's resource policy). Not the deciding pillar here — Operational Excellence and the tension below are. |
| **Performance Efficiency** | Push's advantage is reacting the instant an object lands, and irrelevant to a daily batch with no latency requirement. One real forward-pointer: Lambda has a 15-minute execution ceiling, and 7.1's "scaled-up synthetic payments workload" could eventually push a single invocation close to it, where S3-event-per-file fan-out parallelizes naturally. Not decisive for Phase 2's actual volume, but worth 7.1 re-checking this decision rather than assuming it still holds. |
| **Sustainability** | Follows Cost, as in 0002/0003 — not independently decisive. |

**The tension worth naming — and the one the phase name invites getting
wrong:** "event-driven ingestion" reads as "react to an upstream event," and
an S3 event notification is the mechanism that does that literally. But
`generate_payments.py` *is* the source of the data — it doesn't consume a
file dropped by something else, it generates and writes bronze objects in
one step. Wiring an S3 event notification to the same function that
produces the object it would fire on means either (a) triggering on a write
the Lambda itself just made, which is circular and buys nothing, or (b)
inventing an artificial two-step hand-off — write a "raw drop" first, then
have a second Lambda react to it — solely to make the trigger shape match
the phase's name, with no real upstream producer to justify the extra hop.

That second option is worth taking seriously rather than dismissing
outright, because it names the real trade this ADR is making: Phase 2
exists partly to demonstrate genuine push-reactive architecture — that has
real portfolio and learning value — against architectural honesty, which
says don't build a hop this pipeline doesn't structurally need just to
perform a pattern. This ADR resolves that toward honesty. The cost is
conceded explicitly in the Consequences below, not left unstated: this
phase will not demonstrate a genuinely push-triggered pipeline.

Read narrowly, "event-driven" in this phase is really about *what kind of
infrastructure does the scheduling* — a managed, serverless schedule instead
of a systemd timer tied to one machine's login session — not about
introducing genuine push reactivity where no upstream event exists yet. A
genuine S3-event-triggered path becomes the right decision the day this
pipeline's data source stops being self-produced, or the day a downstream
step (not ingestion itself) needs to react to bronze arriving — e.g. a
later phase's transform running on arrival instead of on its own schedule.
That is a distinct, revisitable decision, not this one; deferred the same
way 0002 deferred a future PII-handling ADR and 0003 picked it back up.

## Decision

**EventBridge Scheduler, invoking the Lambda directly on a daily schedule.**
The schedule's timezone is set explicitly to UTC — not left to default —
because `generate_payments.py` partitions events by UTC event day; an
unconsidered timezone choice here would silently shift which `dt=`
partition a run lands in relative to today's systemd timer (`OnCalendar=daily`,
local time). The Lambda (2.1) wraps `generate_payments.py`'s existing core
logic; the schedule (2.2) replaces `cerberus-payments.timer` +
`run_payments_scheduled.sh`'s trigger role, not the generator itself —
consistent with the checkpoint's existing framing that 2.1 wraps the *same*
generator rather than replacing it, though see the Consequences below on
what "wraps" actually costs.

On IAM: this ADR leans toward giving the Lambda **its own execution role**
with a policy equivalent to `cerberus-ingestion`'s (`s3:PutObject` scoped to
`bronze/payments/*` only), rather than extending `cerberus-ingestion`'s
trust policy to admit it. The two aren't equally cheap: Lambda has no
CLI-style profile-chaining equivalent to `~/.aws/config`'s
`role_arn`/`source_profile`, so reusing `cerberus-ingestion` would mean the
handler explicitly calling `sts:AssumeRole` in code (as `promote_payments.py`
already does for `cerberus-transform`) for no benefit over a role scoped
identically from the start. 2.3 still makes this final — the policy content
is fixed here, the role topology is a lean, not a mandate.

S3 event notifications are explicitly **not** used for triggering the
ingestion Lambda in this phase, for the reason above: there is no upstream
object landing that isn't the ingestion Lambda's own output. This decision
is scoped to *ingestion's* trigger only — it does not foreclose S3 event
notifications for a different, future consumer of bronze's arrivals.

## Consequences

- 2.1's Lambda is invoked on a schedule, not by a storage event. Its handler
  does get one thing from the trigger worth keeping: EventBridge Scheduler's
  invocation payload includes a `time` field, usable as a natural
  idempotency or logging key even though nothing in this design currently
  requires one.
- **"Wraps the existing core logic" is not a thin wrapper.** Three things in
  `generate_payments.py` don't survive the move as-is and 2.1 needs to
  budget for rewriting them: `upload()` shells out to the AWS CLI
  (`subprocess.run(["aws", "s3", "cp", …])`), which doesn't exist in the
  Lambda runtime and must become a boto3 `put_object` call; authentication
  currently goes through a named CLI profile (`AWS_PROFILE =
  "cerberus-ingestion"`), which has no Lambda equivalent — credentials come
  from the execution role instead; and `faker` is a third-party dependency
  requiring a layer or container image. The event/transaction generation
  logic itself (`generate_events()`, `build_roster()`) is what genuinely
  carries over unchanged.
- **At-least-once delivery is a new risk this decision introduces, not a
  free win.** EventBridge Scheduler retries are at-least-once.
  `generate_payments.py`'s RNG is deliberately unseeded
  (`# unseeded: event content varies run to run`) and its S3 keys embed
  `run_ts`, so a retried invocation doesn't re-send the same data — it
  generates and appends a *different* dataset into an append-only bronze
  layer with no reconciliation. This is not the same class of risk as the
  per-partition upload retry the Phase 1 review already fixed by hand in
  `generate_payments.py` (`3bc73d0`), which retries one failed `PutObject`
  without regenerating anything. 2.1 needs to explicitly choose: configure
  the schedule for a single attempt and keep the existing per-partition
  retry as the only retry layer, or design real idempotency if
  invocation-level retry is wanted. Not resolved here.
- **Retirement policy: decided 2026-08-11 to keep a fixed-window
  auto-retirement, on data-volume grounds, not cost.** Priced running the
  schedule for 10 vs. 30 days against this project's actual measured data
  rate: roughly $0.0004 vs. $0.0014 total, negligible against the existing
  $10/month billing alarm — so cost cannot justify a cap at this volume.
  The cap is kept anyway, deliberately, to bound bronze's synthetic dataset
  rather than let it grow unbounded once nobody's actively watching it.
  Where the logic lives once `run_payments_scheduled.sh` is gone — inside
  the Lambda's own date check, or as an infrastructure-level disable of the
  EventBridge schedule — is still open, left to 2.1/2.2.
- 2.5 retires `cerberus-payments.timer` once the Lambda path is verified end
  to end. Note the race: the wrapper already self-disables the timer on/after
  2026-08-17 regardless of this work, so 2.5 may find it already off by the
  time it runs — in which case "retire" means deleting and unlinking the
  systemd unit files, the same shape weather ingestion's retirement took on
  2026-08-07, not disabling an already-disabled timer.
- Closes the systemd-linger blocker for good. A managed EventBridge schedule
  has no login-session dependency to skip or delay against — unlike the
  skipped/delayed runs cited in Context, which are this gap's real,
  already-observed cost.
- This ADR settles triggering the ingestion Lambda only. It does not rule
  out S3 event notifications elsewhere in the pipeline — a later phase's
  transform reacting to bronze arriving is a legitimate, different decision,
  not foreclosed by this one.
- **Conceded cost:** this phase will not demonstrate genuinely push-triggered
  architecture, only a managed pull/schedule. That's a deliberate trade,
  made because there's no real upstream producer yet to react to — not
  because push mechanisms are being avoided on principle. If this pipeline
  ever gains a genuine external, uncontrolled data producer, the
  push-shaped S3 event notification path this ADR rejects for ingestion
  becomes the right one for *that* producer — a future decision, not a
  reversal of this one.
