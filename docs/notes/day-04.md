# Day 04 — Phase 2: Event-Driven Ingestion, ADR to Retirement

_Date: 2026-08-10–2026-08-12 · Project: cerberus-platform · Phase: 2 —
Event-driven ingestion (complete as of today)_

**Purpose of this document.** This is a study note, not a status report —
[checkpoint.md](../../checkpoint.md) already tracks that. The goal here is
to capture the *theory* behind each piece of code written across this
window, with the actual code inline, organized by discipline the way an
engineering curriculum would group it. Read it top to bottom once, then use
it as a reference later.

_Window note: [day-03](day-03.md) already covers everything committed on
the morning of 2026-08-10 (1.9–1.13, Phase 1's close). This note picks up
right after that — the first article and the tagging/PR workflow adoption
later that same evening — through today's close of Phase 2._

## Table of contents

1. [Governance: ADR 0005 — deciding push vs. pull ingestion](#1-governance-adr-0005--deciding-push-vs-pull-ingestion)
2. [Cloud Resources: AWS Lambda & EventBridge Scheduler fundamentals](#2-cloud-resources-aws-lambda--eventbridge-scheduler-fundamentals)
3. [Cloud Security: trust policies — human vs. service principals](#3-cloud-security-trust-policies--human-vs-service-principals)
4. [Data Engineering: a shared library and two real production bugs](#4-data-engineering-a-shared-library-and-two-real-production-bugs)
5. [Infrastructure as Code: the `lambda_ingestion` Terraform module](#5-infrastructure-as-code-the-lambda_ingestion-terraform-module)
6. [Systems Administration: retiring the systemd timer](#6-systems-administration-retiring-the-systemd-timer)
7. [Governance: process discipline — tagging, PR-per-push, and the Well-Architected diff](#7-governance-process-discipline--tagging-pr-per-push-and-the-well-architected-diff)
8. [Glossary](#8-glossary)

---

## 1. Governance: ADR 0005 — deciding push vs. pull ingestion

### Theory

Two new ideas beyond the ADR mechanics [day-01](day-01.md) already covered:

**Push vs. pull as trigger models.** A **pull** trigger is a schedule: some
clock-driven mechanism invokes your code on a timer, whether or not there's
anything new to do (`cerberus-payments.timer`, and its replacement below,
are both pull). A **push** trigger is the opposite: an upstream event —
someone else's write — invokes your code the instant it happens. The two
aren't interchangeable design choices with the same shape; they answer
different questions ("is it time yet?" vs. "did something just happen?"),
and picking the wrong one for your actual data flow produces an
architecture that's honest-looking but structurally wrong.

**At-least-once delivery.** A common guarantee managed schedulers and event
buses offer: if an invocation might have failed, the trigger retries rather
than silently dropping it. This sounds like a pure improvement over "no
retry at all" — but it only is if repeating the invocation is *safe*. If
the retried invocation does something non-idempotent (like generating a
fresh, unseeded batch of data), "at least once" becomes "the underlying
operation might happen more than once," which is a genuinely new failure
mode, not a mitigation of an old one.

### The decision record

ADR 0005 opens by naming a problem that had already happened, not a
hypothetical one — the actual `cerberus-payments.timer` run history:

> `Persistent=true` means missed runs catch up rather than vanish, but the
> actual run timestamps in `payments/dt=*/` show it skipped 2026-08-09
> entirely and ran late on 2026-08-10 (01:12, not 00:00) and 2026-08-11
> (04:09) — the schedule is already degrading, observably, not
> hypothetically.

That evidence requirement is itself worth noting: an earlier draft of this
ADR claimed the catch-up bug had "already fired," which turned out to be
false when checked against the real run timestamps — an Opus review caught
the fabricated claim and the ADR was corrected to cite what had actually
happened (late/skipped runs) instead of what would have been a more
dramatic but untrue story. A design decision resting on a wrong fact is
worse than one resting on no fact, because it looks solid until someone
checks.

The **Reliability** pillar row is where the push/pull tension and the
at-least-once risk both surface in the same paragraph:

> EventBridge Scheduler's native retry policy and flexible time window are
> a real answer to the catch-up/delay behavior already observed above. But
> retry cuts both ways here — see the Consequences section: at-least-once
> delivery against an intentionally unseeded generator is a new risk this
> decision introduces, not a pure win.

> **Why this matters:** this is the ADR method from [checkpoint.md](../../checkpoint.md)'s
> reference section working exactly as designed — the pillar didn't just
> bless the obvious choice, it surfaced a cost the obvious choice
> introduces. That cost becomes a concrete Terraform setting in §5 below
> (`maximum_retry_attempts = 0`), not just a sentence in a document.

The ADR's real substance, though, is the **tension** section — the part
that makes this decision non-obvious. Phase 2 is named "event-driven
ingestion," which reads as "react to an upstream event." But
`generate_payments.py` doesn't consume an externally-produced file — it
*is* the producer. Wiring an S3 event notification to the same function
that creates the object it would fire on is either circular (triggering on
your own write) or requires inventing an artificial two-step hand-off with
no real upstream producer to justify it:

> Read narrowly, "event-driven" in this phase is really about *what kind of
> infrastructure does the scheduling* — a managed, serverless schedule
> instead of a systemd timer tied to one machine's login session — not
> about introducing genuine push reactivity where no upstream event exists
> yet.

**Decision:** EventBridge Scheduler, invoking the Lambda directly on a
daily schedule, UTC timezone fixed explicitly. A genuine S3-event-triggered
path is deferred, not rejected — it becomes correct "the day this
pipeline's data source stops being self-produced."

---

## 2. Cloud Resources: AWS Lambda & EventBridge Scheduler fundamentals

### Theory

Before §5's Terraform, here's what each managed service actually provides —
mirroring [day-01](day-01.md)'s S3 feature table for the same reason: the
`.tf` code below is declaring these concepts, not inventing them.

| Concept | What it is | Why this project uses it |
|---|---|---|
| **Lambda function** | A unit of code AWS runs on demand, with no server for you to provision or patch — you supply a handler function and a runtime, AWS supplies the compute. | Replaces the systemd timer's dependency on *any* machine being on and logged in — the function runs on AWS's infrastructure, not the developer's laptop. |
| **Lambda layer** | A zip of dependencies, attached to a function separately from its own code, extracted to `/opt` inside the execution environment. | `faker` is a third-party dependency with no place to live in a bare Lambda zip; a layer keeps it out of the function's own deployment package. |
| **Execution role** | The IAM role a Lambda function runs *as* — every AWS API call the code makes is authorized against this role, not against whoever deployed the function. | See §3 — this is where the "assumed by a service, not a human" distinction actually matters operationally. |
| **EventBridge Scheduler** | A managed cron/rate scheduler, the modern successor to CloudWatch Events "scheduled rules." Invokes a target (here, the Lambda) on a schedule expression, using its own execution role to do so. | Chosen specifically over a legacy scheduled rule because Scheduler natively supports retry policies, dead-letter queues, and flexible time windows — direct answers to the reliability gap in §1. |
| **`flexible_time_window`** | An optional jitter window Scheduler can spread invocations across, instead of firing every instance at the exact same second. | Set to `mode = "OFF"` here — a single daily payments-generation run has no reason to jitter; this project has no fleet of identical invocations that would benefit from spreading load. |
| **`retry_policy` / `maximum_retry_attempts`** | How many times Scheduler retries a failed invocation of its target before giving up. | Set to `0` — the direct Terraform expression of §1's Consequences finding: a retry here would regenerate a different, unseeded dataset, not safely repeat the same one. |

> **Why this matters:** EventBridge Scheduler needs **its own** execution
> role, separate from the Lambda's — one authorizes Scheduler to call
> `lambda:InvokeFunction`, the other authorizes the Lambda's own code to
> call `s3:PutObject`. Conflating them would be a real IAM mistake: two
> completely different principals (`scheduler.amazonaws.com` calling in,
> the function's own code calling out) with no reason to share a policy.

---

## 3. Cloud Security: trust policies — human vs. service principals

### Theory

[day-02](day-02.md) already covered IAM roles, trust policies, and
least-privilege scoping for this project's first three roles — all three
trusted by the same human principal (`cerberus-admin`, assumed by hand via
`aws sts assume-role`). This window adds a genuinely new shape: a role
trusted by an **AWS service** instead.

An IAM role's **trust policy** (the `assume_role_policy` attribute) answers
one question: *who is allowed to assume this role?* The `Principal` field
is where that's declared, and it comes in different flavors:

- **`Principal = { AWS = "<ARN>" }`** — a specific IAM user, role, or
  account is trusted. This is what `cerberus-ingestion`/`cerberus-transform`/
  `cerberus-serving` use: a human (or anything else holding
  `cerberus-admin`'s credentials) calls `sts:AssumeRole` explicitly and
  receives temporary credentials in return.
- **`Principal = { Service = "<service>.amazonaws.com" }`** — an AWS
  service itself is trusted, not a person. When that service performs the
  action that needs the role (here: Lambda invoking a function), AWS
  assumes the role on the service's behalf automatically — there's no
  `sts:AssumeRole` call for anyone to make by hand, and no credentials to
  chain through a CLI profile.

This is why `cerberus-ingestion-lambda` is a **fourth**, separate role
rather than an extension of `cerberus-ingestion`'s existing trust policy:
Lambda has no equivalent of `~/.aws/config`'s `role_arn`/`source_profile`
chaining, so admitting the Lambda into `cerberus-ingestion`'s trust policy
would just mean writing an explicit `sts:AssumeRole` call inside the
handler for no benefit over a role scoped identically and trusted by
`lambda.amazonaws.com` from the start.

### The code

`terraform/modules/iam/main.tf` — the new role's trust policy, same
`s3:PutObject` scope as `cerberus-ingestion` but a different principal
type:

```hcl
resource "aws_iam_role" "ingestion_lambda" {
  name = "cerberus-ingestion-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "ingestion_lambda" {
  name = "cerberus-ingestion-lambda-policy"
  role = aws_iam_role.ingestion_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WritePaymentsToBronze"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${var.bucket_arns["bronze"]}/payments/*"
      }
    ]
  })
}
```

The inline policy is a direct copy of the scoping pattern day-02 already
established — `s3:PutObject` on `bronze/payments/*` only, nothing broader.
What's new is the one exception to this module's "inline policies only"
convention, made explicitly rather than silently:

```hcl
resource "aws_iam_role_policy_attachment" "ingestion_lambda_logs" {
  role       = aws_iam_role.ingestion_lambda.id
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
```

`aws_iam_role_policy_attachment` attaches an AWS **managed** policy (one
AWS owns and updates, referenced by ARN) rather than declaring the
permissions inline. The reasoning, straight from the module's own comment:
`AWSLambdaBasicExecutionRole` grants `CreateLogGroup`/`CreateLogStream`/
`PutLogEvents` — boilerplate every Lambda needs for CloudWatch Logs, not a
project-specific data-plane grant. The "inline only" convention is about
not standing up a bespoke `aws_iam_policy` for something that's 1:1 with a
single role anyway; it isn't a blanket objection to AWS's own managed
policies for genuinely standard runtime plumbing.

---

## 4. Data Engineering: a shared library and two real production bugs

### Theory

**Extracting a shared library.** When the same logic needs to run from two
different entry points — here, a CLI script triggered by a human/systemd,
and a Lambda handler triggered by a scheduler — the choice is between
duplicating the logic in both places (drift risk: a fix in one place
silently doesn't apply to the other) or extracting the shared core into a
module both entry points import. The two entry points genuinely differ
only in *how they're invoked, authenticated, and logged* — not in what they
generate — which is exactly the signal that a shared library is the right
cut, not a premature abstraction.

**Tie-breaking a "latest wins" resolution.** A common pattern for deriving
current state from an event log is "take the row with the max timestamp per
key." That's only correct if timestamps are strictly increasing within a
key. §4's bug is a concrete case where they aren't: `generate_payments.py`
clamps every event's timestamp to `min(computed_ts, now)` (day-01, §2), so
if a transaction's `settled` and `refunded` events are both computed to
land after the moment the script actually ran, both get clamped to the
*same* `now` value — a genuine tie, not a rounding artifact. Sorting on
timestamp alone at that point returns whichever row happens to sort last,
which is not necessarily the true latest event.

**Retryable vs. non-retryable errors.** Not every failed API call deserves
a retry. `AccessDenied` and `NoSuchBucket` will fail exactly the same way
on attempt 10 as attempt 1 — retrying them wastes time (costly inside a
Lambda's execution-time budget) without any chance of success. A
well-designed retry policy distinguishes error *classes*: transient
failures (throttling, brief network issues, some 5xx responses) are worth
retrying with backoff; permanent failures are not.

### The code

**Extraction.** `ingestion/scripts/payments_lib.py` is the new shared
module — its own docstring states the design plainly:

```python
"""Cerberus 1.3/2.1 — shared synthetic payments generation core.

Pure generation logic (roster, event lifecycle, day-partitioning) plus a
boto3-based upload helper, shared between the CLI script
(generate_payments.py, for manual/systemd-triggered runs) and the Lambda
handler (../lambda/handler.py, for the EventBridge-scheduled path — 2.1,
ADR 0005). Kept free of argparse/Lambda specifics so both callers can
import it unchanged; each caller supplies its own boto3 S3 client, since
the two run under different credentials (a chained CLI profile vs. a
Lambda execution role) -- callers should build that client with
S3_CLIENT_CONFIG below so retries are handled consistently.
"""
```

**The retryable-errors fix**, applied once at client construction rather
than as a hand-rolled loop around every call site:

```python
UPLOAD_MAX_ATTEMPTS = 3

# "standard" mode retries with exponential backoff, and only on genuinely
# retryable error codes (throttling, transient 5xx, timeouts) -- unlike a
# hand-rolled retry loop around bare ClientError, it won't waste attempts
# retrying something like AccessDenied or NoSuchBucket that can never
# succeed. Applied at the client level (see callers), not per-call.
S3_CLIENT_CONFIG = Config(retries={"total_max_attempts": UPLOAD_MAX_ATTEMPTS, "mode": "standard"})
```

Both callers build their S3 client with this `Config` object
(`boto3.client("s3", config=S3_CLIENT_CONFIG)`), and `upload_day` itself
collapses to a single `try`/`except` — no manual retry counter, no manual
backoff sleep:

```python
def upload_day(s3_client, bucket, day, day_events, run_ts, log=print):
    body = json.dumps(day_events).encode("utf-8")
    s3_key = f"payments/dt={day}/payments_{run_ts}.json"
    try:
        s3_client.put_object(
            Bucket=bucket, Key=s3_key, Body=body,
            ContentType="application/json",
        )
        log(f"[{iso(datetime.now(timezone.utc))}] uploaded s3://{bucket}/{s3_key} ({len(day_events)} events)")
        return True
    except ClientError as exc:
        log(f"[{iso(datetime.now(timezone.utc))}] upload for {day} failed ({exc}) -- {len(day_events)} events for this partition were NOT saved")
        return False
```

> **The one real gotcha:** the *original* version of this code (committed
> earlier the same window, `3bc73d0`) already fixed the "one failed day
> aborts the whole run" bug with a hand-rolled retry loop — but that loop
> retried on *any* `ClientError`, including permanent ones. It took reading
> the `aws-sdk-python-usage` skill's reference content directly (the skill
> itself couldn't be invoked live — a plugin installed mid-session doesn't
> hot-load into that session's skill registry) to catch that the fix
> worked, but was still wasting retry attempts on errors that could never
> succeed no matter how many times they were retried.

**The tiebreak fix**, in both places that resolve "current state" from the
event log. `transform/scripts/promote_payments.py`:

```python
# generate_payments.py clamps every event's timestamp to min(ts, now), so a
# transaction whose settle and refund events both land after "now" gets
# identical event_timestamp strings for the two -- sorting on timestamp
# alone is not enough to pick the true latest event. This fixed lifecycle
# order (created -> authorized -> settled/failed -> refunded) breaks that
# tie deterministically; settled/failed share a rank since a transaction
# only ever emits one of the two.
EVENT_TYPE_RANK = {
    "created": 0,
    "authorized": 1,
    "settled": 2,
    "failed": 2,
    "refunded": 3,
}
```

```python
def write_gold(s3, df):
    ranked = df.assign(_rank=df["event_type"].map(EVENT_TYPE_RANK))
    latest = (
        ranked.sort_values(["event_timestamp", "_rank"])
        .groupby("transaction_id")
        .tail(1)
        .drop(columns="_rank")
    )
    write_parquet(s3, latest, GOLD_BUCKET, "payments_current/current_state.parquet")
```

Sorting by `["event_timestamp", "_rank"]` and taking `.tail(1)` means: sort
primarily by timestamp, and among rows that tie on timestamp, the higher
`_rank` (later lifecycle stage) sorts last and wins. The dbt model gets the
identical fix expressed as a SQL window function instead of a pandas sort:

```sql
row_number() over (
    partition by transaction_id
    order by
        event_timestamp desc,
        case event_type
            when 'refunded' then 3
            when 'settled' then 2
            when 'failed' then 2
            when 'authorized' then 1
            when 'created' then 0
        end desc
) as rn
```

`order by event_timestamp desc, case ... end desc` is SQL's equivalent of a
composite sort key — ties on the first key are broken by the second. Same
logic, two different engines, kept in sync by hand (there's no shared
constant between the Python dict and the SQL `case` expression, a small,
acknowledged gap noted in the review that found this bug).

> **Why this matters:** this bug was live in production data before it was
> caught — 15 transactions in gold were mislabeled `settled` instead of
> `refunded`. It's a good example of a class of bug that's easy to miss by
> reading code in isolation (the sort *looks* correct) and easy to catch by
> checking assumptions against the actual upstream data (the clamp in
> `generate_payments.py` that makes ties possible in the first place).

---

## 5. Infrastructure as Code: the `lambda_ingestion` Terraform module

### Theory: two HCL mechanics not seen in day-01

**`data "archive_file"`** — a data source (day-01, §5.3) provided by the
`hashicorp/archive` provider, not `hashicorp/aws`. It zips a set of source
files into an output path at plan/apply time and exposes that zip's
attributes (path, base64-encoded SHA256 hash) for other resources to
reference. It doesn't create or manage anything in AWS — it's local file
packaging, expressed declaratively instead of via a separate build script.

**`null_resource` + the `local-exec` provisioner.** Terraform's resource
model assumes every resource corresponds to something a provider's API can
create, read, update, and delete. Installing Python packages with `pip` is
none of those things — there's no `aws_pip_install` resource type, because
`pip install` isn't an AWS API call at all. `null_resource` is Terraform's
escape hatch for exactly this gap: a resource with no real infrastructure
behind it, whose only job is to run an arbitrary local shell command
(`local-exec`) as a side effect, gated by its own `triggers` map instead of
provider-diffable attributes.

### The code

**Packaging the function itself** — `handler.py` and `payments_lib.py`
flattened into one zip so they import as siblings once Lambda unzips them:

```hcl
data "archive_file" "function" {
  type        = "zip"
  output_path = "${path.module}/build/ingest_payments.zip"

  source {
    content  = file("${path.module}/../../../ingestion/lambda/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../../../ingestion/scripts/payments_lib.py")
    filename = "payments_lib.py"
  }
}
```

**Building the Faker layer** — the one place this project's Terraform
shells out, called out explicitly in the module's own comment as a
deliberate, scoped exception rather than a habit:

```hcl
resource "null_resource" "build_layer" {
  triggers = {
    requirements_hash = filemd5("${path.module}/../../../ingestion/lambda/requirements.txt")
  }

  provisioner "local-exec" {
    command = "${path.module}/../../../.venv/bin/pip install -r ${path.module}/../../../ingestion/lambda/requirements.txt -t ${path.module}/build/layer/python --no-cache-dir --quiet"
  }
}

data "archive_file" "faker_layer" {
  type        = "zip"
  source_dir  = "${path.module}/build/layer"
  output_path = "${path.module}/build/faker_layer.zip"

  depends_on = [null_resource.build_layer]
}
```

`triggers = { requirements_hash = filemd5(...) }` is `null_resource`'s
substitute for the change-detection every real resource gets for free:
since there's no provider API to diff against, Terraform instead re-runs
the provisioner only when this map's value changes — here, only when
`requirements.txt`'s content hash changes, not on every `apply`.

The `depends_on = [null_resource.build_layer]` on `data.archive_file.faker_layer`
is worth connecting back to day-01's implicit-dependency theory (§5.4
there): Terraform normally infers ordering by seeing one resource reference
another's computed attribute. But `data.archive_file.faker_layer` reads
`source_dir` from the *filesystem*, not from any attribute of
`null_resource.build_layer` — there's nothing for Terraform to notice, so
without an **explicit** `depends_on`, it could zip the layer directory
before `pip install` has populated it. This is the specific, narrow case
`depends_on` exists for: a real ordering requirement Terraform's normal
attribute-reference inference can't see on its own.

**Wiring it into the function**, then the scheduler's own execution role
and the schedule itself — put together, this is §2's and §3's concepts
becoming real resources:

```hcl
resource "aws_lambda_function" "ingest_payments" {
  function_name = "cerberus-ingest-payments"
  role          = var.execution_role_arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  filename         = data.archive_file.function.output_path
  source_code_hash = data.archive_file.function.output_base64sha256

  layers = [aws_lambda_layer_version.faker.arn]

  environment {
    variables = {
      BRONZE_BUCKET      = var.bronze_bucket_name
      RETIRE_ON_OR_AFTER = var.retire_on_or_after
      TRANSACTION_COUNT  = tostring(var.transaction_count)
    }
  }
}
```

```hcl
resource "aws_scheduler_schedule" "daily" {
  name       = "cerberus-ingest-payments-daily"
  group_name = "default"

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.ingest_payments.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
```

`source_code_hash = data.archive_file.function.output_base64sha256` is why
`terraform apply` picks up a code change automatically: Terraform diffs
this hash against what's already deployed, and a changed hash is what
triggers a new `UpdateFunctionCode` call — no separate "redeploy" step
exists outside the normal `plan`/`apply` cycle. `role_arn =
aws_iam_role.scheduler.arn` inside the `target` block is Scheduler's own
execution role (§2's second role, distinct from the Lambda's) — the
resource being configured here is *what Scheduler is allowed to invoke*,
not what the Lambda is allowed to do once invoked.

> **Verified live, not just planned:** applying this module (9 resources,
> 0 changed/destroyed on the existing IAM/S3 resources) was followed by a
> manual `aws lambda invoke`, confirming a real object landed in
> `bronze/payments/`, plus `iam simulate-principal-policy` runs confirming
> both that Scheduler's role can actually call `lambda:InvokeFunction` and
> that the execution role's boundaries match `cerberus-ingestion`'s exactly
> (allowed on `bronze/payments/*`, denied elsewhere in bronze, denied on
> gold).

---

## 6. Systems Administration: retiring the systemd timer

### Theory

[day-01](day-01.md), §3 already covers `.service`/`.timer` unit theory,
including `Persistent=true`'s catch-up behavior. This window supplied the
live confirmation of that theory's failure mode, and then the teardown.

Retiring a systemd `--user` unit that's currently enabled and active is a
small, ordered sequence: **disable** (remove it from the target that would
start it on boot/login — `timers.target` here), **stop** (if currently
running/waiting), **unlink** the symlinks under `~/.config/systemd/user/`
that point at the real unit files, and **reload** the systemd user daemon
so it forgets the unit definitions entirely. Doing these out of order (e.g.
deleting the real unit files before unlinking the symlinks pointing at
them) leaves systemd holding broken references.

### What changed

First, live evidence that the theory in ADR 0005's Context section wasn't
hypothetical — checked via `systemctl --user status` on this session's
login, *before* any retirement action was taken:

```
● cerberus-payments.timer - Run cerberus synthetic payments generator daily
     Active: active (waiting) since Wed 2026-08-12 04:41:09 UTC; 2h 1min ago
    Trigger: Thu 2026-08-13 00:00:00 UTC; 17h left
```

The timer's *own* record showed it last ran at `04:41:09 UTC` — not
midnight, its `OnCalendar=daily` schedule — because `Persistent=true`
queued a catch-up run the moment this session's login restarted the
`--user` systemd instance, exactly the login-session dependency ADR 0005
named as the reason to move off it. The retirement sequence itself:

```bash
systemctl --user disable --now cerberus-payments.timer
# then, separately, the service's symlink (disable --now only removed
# the timer's):
rm ~/.config/systemd/user/cerberus-payments.service
systemctl --user daemon-reload
```

`disable --now` combines "remove from `timers.target.wants/`" (so it won't
start on the next login) with "stop it right now" in one command. The
service's own symlink under `~/.config/systemd/user/` needed a second,
explicit removal — `disable` only unregisters the *timer* from the target
that would trigger it, not the separate `.service` symlink the timer
points at. `daemon-reload` tells systemd to re-scan its unit definitions,
clearing the now-stale `cerberus-payments.timer` from `systemctl --user
status`'s output entirely (it reports "could not be found" afterward,
rather than "inactive").

Finally, the actual unit files — no longer symlinked from anywhere — were
deleted from the repo:

```bash
rm ingestion/systemd/cerberus-payments.service ingestion/systemd/cerberus-payments.timer
```

`generate_payments.py`, `payments_lib.py`, and `run_payments_scheduled.sh`
were deliberately left untouched — the same "self-retiring, not
self-deleting" shape day-01 documented for the wrapper script itself, and
the same scope weather ingestion's 2026-08-07 retirement used: delete the
*trigger*, keep the code runnable by hand.

> **Why this matters:** the EventBridge Scheduler path (§2) was confirmed
> firing genuinely unattended — a real invocation at `2026-08-12T00:00:09Z`
> with no manual trigger, 8 partitions written — *before* any retirement
> action was taken. Retiring the fallback only after independently
> verifying its replacement is what makes the ADR 0005 decision more than a
> plan on paper.

---

## 7. Governance: process discipline — tagging, PR-per-push, and the Well-Architected diff

### Theory

**Annotated git tags.** A git tag is a named pointer to a specific commit.
**Lightweight** tags are just that pointer; **annotated** tags (`git tag
-a`) additionally store a message, tagger identity, and date — closer to a
small, immutable object than a bare label. `git tag -n99` prints those
messages:

```
v0-foundation   Phase 0 — Foundation (built by hand): repo scaffold, AWS
                account hygiene + billing alarm, manual S3 bronze bucket,
                bash+systemd ingestion, manual Terraform state backend.
v1-mvp          Phase 1 — MVP: end-to-end lakehouse. Synthetic payments ->
                bronze -> transform -> silver/gold -> Glue Catalog -> dbt
                fact/dimension marts -> Athena, all provisioned by
                terraform apply and verified live (destroy/apply, demo
                query, Well-Architected review ADR 0004).
```

An annotated tag's message is what makes it a genuine milestone record, not
just a bookmark — `git show v1-mvp` surfaces that description on its own,
without needing to cross-reference `checkpoint.md`.

**Branching strategy as a tradeoff, not a fixed rule.** `docs/plan.md`'s
guiding principle 8 went through two shapes in this window alone:
branch-per-phase/PR-per-phase (one PR bundling an entire phase's work,
adopted 2026-08-10) was abandoned the very next day for **PR-per-push**
(every subtask, fix, or finding ships on its own branch, merged same-day).
The tradeoff is real in both directions: batching a whole phase into one PR
produces a cleaner single review unit but reads as long silences between
visible commits; a PR per unit of work reads as continuous activity but
means each PR is reviewed (here, by the same person who wrote it) in
isolation from the phase's full context. Neither is objectively correct —
this project picked visible daily activity, explicitly, as a portfolio
consideration.

**Diffing against a Well-Architected milestone**, rather than re-answering
all 57 questions every phase. [day-03](day-03.md)'s Governance section
already covers what the Well-Architected Tool *is* and how milestone 1 was
first created; new this window is the actual **diff workflow**: fetch an
existing answer, re-answer only the ones with genuinely new evidence, save
a second milestone, and let the tool's own risk-count delta become the
artifact.

### The commands

This window's branch → PR → merge cycle, run for real (shown here for the
smallest of this window's four PRs, a one-line ADR status fix — the same
shape scales to larger changes):

```bash
git checkout -b fix-adr-0006-status
git add docs/adr/0006-phase-2-well-architected-review.md
git commit -m "Fix ADR 0006 status to Accepted, matching ADR 0004's precedent"
git push -u origin fix-adr-0006-status

gh pr create --title "Fix ADR 0006 status to Accepted, matching ADR 0004's precedent" --body "..."
gh pr merge --merge <pr-number>

git checkout main && git pull origin main
git branch -d fix-adr-0006-status
```

`gh pr merge --merge` performs a **regular merge** (a merge commit,
preserving both branches' individual commits in history) — the explicit
alternative to `--squash`, which this project's principle 8 rules out by
name, since squashing would flatten exactly the granular history
PR-per-push is trying to keep visible.

The Well-Architected diff, run against the workload created in day-03,
re-answering one question with concrete new evidence:

```bash
aws wellarchitected update-answer \
  --workload-id 58c236e2c7844375965d22349b460084 \
  --lens-alias wellarchitected \
  --question-id select-service \
  --selected-choices cost_select_service_requirements cost_select_service_analyze_all \
    cost_select_service_thorough_analysis cost_select_service_select_for_cost \
    cost_select_service_licensing cost_select_service_analyze_over_time \
  --notes "ADR 0005 added a real different-usage-over-time analysis: priced the \
EventBridge/Lambda ingestion path at 10 vs. 30 days against measured data rates \
before deciding to keep the 10-day cap on data-volume grounds, not cost."

aws wellarchitected create-milestone \
  --workload-id 58c236e2c7844375965d22349b460084 \
  --milestone-name "phase-2-event-driven-ingestion-complete"
```

`update-answer` takes the full replacement set of `--selected-choices` for
a question — not a delta — so re-answering means re-listing every choice
that should remain selected, plus whatever's newly true. `create-milestone`
takes only a name; it snapshots the *current* state of every answer in the
workload, not just the ones just touched — which is exactly why it's safe
to call once at the end, after re-answering only the handful of questions
with real new evidence, rather than needing to touch all 57.

> **Why this matters:** the milestone diff (26 HIGH / 19 MEDIUM / 7 NONE / 5
> N/A → 26 HIGH / **18** MEDIUM / **8** NONE / 5 N/A) is a small, honest
> number — one question genuinely improved (`select-service`, MEDIUM →
> NONE), two others gained real evidence without crossing the tool's risk
> threshold. That's the intended shape: a phase whose scope is an ingestion
> trigger swap was never going to move Operational Excellence's
> organizational questions or Reliability's multi-AZ gap, and the diff
> says so honestly instead of padding it.

---

## 8. Glossary

| Term | Definition |
|---|---|
| **Push trigger** | An invocation caused by an upstream event (e.g. a storage write) happening — reactive by nature. |
| **Pull trigger** | An invocation caused by a schedule checking in, whether or not there's new work — proactive/periodic by nature. |
| **At-least-once delivery** | A guarantee that a triggered invocation will happen one or more times, never zero — safe only if the invoked operation is idempotent or side-effect-free on repeat. |
| **Lambda layer** | A separately-versioned zip of dependencies attached to a Lambda function, extracted to `/opt` at runtime. |
| **Execution role** | The IAM role a Lambda function's code runs as; authorizes the function's own outbound AWS API calls. |
| **EventBridge Scheduler** | AWS's managed cron/rate scheduler service; the modern replacement for CloudWatch Events scheduled rules. |
| **Trust policy** | An IAM role's `assume_role_policy` — declares which principal(s) are allowed to assume the role. |
| **Service principal** | A `Principal.Service` entry in a trust policy (e.g. `lambda.amazonaws.com`) — an AWS service, not a human, is trusted to assume the role. |
| **Managed policy** | An IAM policy AWS (or another account) owns and maintains, referenced by ARN and attached rather than declared inline. |
| **`data "archive_file"`** | A `hashicorp/archive` provider data source that zips local files/directories into an output path Terraform can reference. |
| **`null_resource`** | A Terraform resource with no real infrastructure backing it, used to run arbitrary local commands via a provisioner, gated by a `triggers` map. |
| **`local-exec` provisioner** | Runs a shell command on the machine running Terraform, as a side effect of a resource's creation. |
| **`depends_on`** | An explicit dependency declaration, used when Terraform can't infer ordering from a resource-attribute reference (e.g. a data source reading the filesystem, not another resource's output). |
| **Annotated git tag** | A tag (`git tag -a`) storing a message, tagger, and date — distinct from a lightweight tag, which is just a named pointer to a commit. |
| **Regular merge** | A merge that creates a merge commit preserving the source branch's individual commits, as opposed to a squash merge that flattens them into one. |
