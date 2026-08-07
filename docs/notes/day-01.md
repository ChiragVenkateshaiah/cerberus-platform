# Day 01 — Payments Ingestion & Infrastructure as Code

_Date: 2026-08-07 · Project: cerberus-platform · Phase: 1 — MVP: end-to-end
lakehouse_

**Purpose of this document.** This is a study note, not a status report —
[checkpoint.md](../../checkpoint.md) already tracks that. The goal here is
to capture the *theory* behind each piece of code written today, with the
actual code inline, organized by discipline the way an engineering
curriculum would group it. Read it top to bottom once, then use it as a
reference later.

## Table of contents

1. [Governance: Architecture Decision Records](#1-governance-architecture-decision-records)
2. [Data Engineering: the synthetic payments generator](#2-data-engineering-the-synthetic-payments-generator)
3. [Systems Administration: scheduling with systemd](#3-systems-administration-scheduling-with-systemd)
4. [Cloud Resources: AWS S3 fundamentals](#4-cloud-resources-aws-s3-fundamentals)
5. [Infrastructure as Code: Terraform](#5-infrastructure-as-code-terraform)
6. [Tooling decisions: Terraform vs. OpenTofu](#6-tooling-decisions-terraform-vs-opentofu)
7. [Glossary](#7-glossary)

---

## 1. Governance: Architecture Decision Records

### Theory

An **ADR (Architecture Decision Record)** is a short document that captures
one significant technical decision: the context that forced it, the decision
itself, and the consequences accepted in exchange. The point isn't
ceremony — it's that six months from now, nobody has to reverse-engineer
*why* something is shaped the way it is from the code alone. The standard
template (Michael Nygard's) has four sections: **Status**, **Context**,
**Decision**, **Consequences**.

ADRs move through a lifecycle: `Proposed` → `Accepted` (or `Rejected`) →
eventually `Superseded` by a later ADR. Today's work moved two ADRs from
`Proposed` to `Accepted`:

- **ADR 0002** — medallion layout (bucket topology, partitioning, file
  formats). This is the ADR that everything in §5 below directly
  implements.
- **ADR 0003** — synthetic payments data model (entity shape, event
  semantics, PII handling). This is the ADR that §2 below directly
  implements.

### What changed

A one-line edit per file — flipping the `## Status` section:

```diff
 ## Status

-Proposed
+Accepted
```

...applied to both `docs/adr/0002-medallion-layout.md` and
`docs/adr/0003-synthetic-payments-data-model.md`, plus checking off their
matching subtasks (1.1, 1.2) in `Phases.md`.

**Why this matters for IaC specifically:** every resource attribute you'll
see in the Terraform code below (three buckets vs. one, daily partitions,
raw JSON vs. Parquet, the 30-day lifecycle transition) is not an arbitrary
choice — it's a direct encoding of a decision that was argued through the
AWS Well-Architected pillars in ADR 0002 *before* a single line of HCL was
written. Infrastructure-as-code without a preceding decision record just
moves the "why did we do it this way" problem into `git blame` archaeology.

---

## 2. Data Engineering: the synthetic payments generator

### Theory

A **synthetic data generator** produces fake-but-realistic records so a
pipeline can be built and tested before a real data source exists. The
craft is in the *shape* of realism: volume, referential structure (the same
merchant should appear in many transactions, not a fresh one each time),
and temporal behavior (events don't all happen at once — they arrive with
delays, and some fail).

ADR 0003 fixed the design before any code was written:

- **One denormalized event per lifecycle step** — not "a transaction row
  that gets updated." A payment's life is `created` → `authorized` →
  `settled`/`failed` → optionally `refunded`, and each step is its own
  immutable JSON object, never an edit of a previous one. This is a direct
  consequence of ADR 0002 deciding bronze must be **append-only**.
- **A small, fixed roster** of merchants/customers, reused across many
  transactions — otherwise joins in later phases (dbt models, Athena
  queries) would be degenerate (every row joins to a unique dimension row,
  which is not how real traffic behaves).
- **Pre-masked PII-shaped fields** — never generate something that looks
  like a real card number or a real person, even as fake data.

### The code

`ingestion/scripts/generate_payments.py` (Python 3, dependency: `Faker`,
pinned in `ingestion/requirements.txt`).

**Deterministic roster.** The trick that makes "small, fixed roster, reused
across runs" possible is *seeding* both the RNG and the Faker instance with
the same constant every time the script runs:

```python
ROSTER_SEED = 42
MERCHANT_COUNT = 15
CUSTOMER_COUNT = 75

def build_roster():
    """Deterministic merchant/customer roster, stable across runs."""
    rng = random.Random(ROSTER_SEED)
    fake = Faker()
    fake.seed_instance(ROSTER_SEED)

    merchants = [
        {
            "merchant_id": f"mrc_{i:04d}",
            "name": fake.company(),
            "category": rng.choice(MERCHANT_CATEGORIES),
        }
        for i in range(1, MERCHANT_COUNT + 1)
    ]
    ...
    return merchants, customers
```

A seeded `random.Random(42)` (or a seeded `Faker`) is a pseudo-random
generator that produces the exact same sequence of "random" values every
time it's constructed with that seed. Run this function today, run it again
next week — `merchant mrc_0007` is the same company both times. That's what
"deterministic" means here: not fixed data, but *reproducible* data.
Compare that to `main()`'s event generation, which deliberately uses an
**unseeded** RNG (`random.Random()` with no argument) — the roster must be
stable, but the *events* should differ every run, or every scheduled run
would just re-upload the same transactions.

**Modeling append-only lifecycle events.** Each transaction is a closure
over shared fields (`transaction_id`, `amount`, `merchant`, ...), with an
inner function stamping out one immutable event per lifecycle step:

```python
def event(event_type, ts):
    return {
        "transaction_id": transaction_id,
        "event_type": event_type,
        "event_timestamp": iso(min(ts, now)),
        "amount": amount,
        "currency": currency,
        "merchant": merchant,
        "customer": customer,
        "payment_method": payment_method,
    }

events.append(event("created", created_ts))

auth_ts = min(created_ts + timedelta(seconds=rng.randint(*AUTH_DELAY_SECONDS)), now)
events.append(event("authorized", auth_ts))

if rng.random() < DECLINE_PROBABILITY:
    events.append(event("failed", auth_ts + timedelta(seconds=rng.randint(1, 30))))
    continue  # no settlement, no refund — this transaction's story ends here

settle_ts = min(auth_ts + timedelta(hours=rng.randint(*SETTLE_DELAY_HOURS)), now)
events.append(event("settled", settle_ts))

if rng.random() < REFUND_PROBABILITY:
    refund_ts = settle_ts + timedelta(days=rng.randint(*REFUND_DELAY_DAYS))
    events.append(event("refunded", min(refund_ts, now)))
```

Every timestamp is `min(computed, now)` — clamped so nothing ever lands in
the future relative to when the script ran. `SETTLE_DELAY_HOURS = (1, 72)`
means a `settled` event can land up to 3 days after its `created` event.

**Why that clamp matters for partitioning.** Bronze is partitioned by the
day an event *occurred*, per ADR 0002 — `payments/dt=YYYY-MM-DD/`. Because
`created` and `settled` for the same transaction can be days apart, **a
single run of this script legitimately writes into multiple day
partitions.** That's not a bug to fix; it's ADR 0003's example
("a `settled` event three days after `created` lands in its own day's
partition") made concrete:

```python
def partition_by_day(events):
    by_day = defaultdict(list)
    for event in events:
        day = event["event_timestamp"][:10]   # "2026-08-05T14:03:00Z" -> "2026-08-05"
        by_day[day].append(event)
    return by_day
```

**Landing the data.** Rather than a Python S3 SDK (`boto3`), the upload
shells out to the AWS CLI — matching the style already established by the
Phase 0 bash script, and avoiding an extra dependency:

```python
def upload(day, day_events, run_ts):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(day_events, f)
        tmp_path = f.name
    try:
        s3_key = f"payments/dt={day}/payments_{run_ts}.json"
        subprocess.run(
            ["aws", "s3", "cp", tmp_path, f"s3://{BUCKET}/{s3_key}",
             "--profile", AWS_PROFILE, "--region", AWS_REGION,
             "--content-type", "application/json"],
            check=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

`check=True` makes `subprocess.run` raise if the `aws` command exits
non-zero — a failed upload fails the script loudly instead of silently
continuing. The `finally` block guarantees the temp file is cleaned up
whether the upload succeeds or raises.

**Result verified today:** a manual run with `--count 200` produced 603
events spread across 8 day partitions, confirmed in S3 via `aws s3 ls`.

---

## 3. Systems Administration: scheduling with systemd

### Theory

**systemd** is the init system and service manager on most modern Linux
distributions (including this Ubuntu 24.04 box). Two unit types matter
here:

- A **`.service` unit** describes *what to run* — a single command
  (`ExecStart`), plus metadata about how to run it. `Type=oneshot` means
  "run once and exit," as opposed to a long-running daemon.
- A **`.timer` unit** describes *when* to run its matching service —
  `OnCalendar=daily` fires once a day; `Persistent=true` means if the
  machine was off when a run was due, it fires once on next boot instead of
  silently skipping it.

Running these as **`--user`** units (`systemctl --user ...`) rather than
system-wide units means they run as the logged-in user, no root required —
appropriate for a personal project, at the cost of needing **linger**
enabled (`loginctl enable-linger`) for them to keep firing after logout.

### The code

`ingestion/systemd/cerberus-payments.service`:

```ini
[Unit]
Description=Cerberus bronze ingestion (synthetic payments generator)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/chira/projects/cerberus
ExecStart=/home/chira/projects/cerberus/ingestion/scripts/run_payments_scheduled.sh
```

`ingestion/systemd/cerberus-payments.timer`:

```ini
[Unit]
Description=Run cerberus synthetic payments generator daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Note the service's `ExecStart` doesn't point directly at
`generate_payments.py` — it points at a **wrapper script**. That
indirection exists to solve a cost problem: an unbounded daily generator
would keep piling up synthetic data (and S3 storage cost) forever, but the
generator script itself needs to stay usable for manual runs indefinitely.
Rather than putting an expiry date inside the generator (which would make
*manual* runs stop working too, defeating the point), the expiry logic
lives one layer up, in the thing that's *only* invoked automatically:

`ingestion/scripts/run_payments_scheduled.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/home/chira/projects/cerberus"
RETIRE_ON_OR_AFTER="2026-08-17"
TODAY="$(date -u +%F)"

if [[ "$TODAY" < "$RETIRE_ON_OR_AFTER" ]]; then
  exec "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/ingestion/scripts/generate_payments.py" "$@"
fi

echo "[$(date -u +%FT%TZ)] retirement date reached ($RETIRE_ON_OR_AFTER) — disabling cerberus-payments.timer."
systemctl --user disable --now cerberus-payments.timer
```

Two bash details worth knowing:

- `set -euo pipefail` is the standard "fail loudly" preamble: `-e` exits on
  any command error, `-u` errors on undefined variables, `-o pipefail`
  makes a pipeline fail if *any* stage fails (not just the last one).
- `[[ "$TODAY" < "$RETIRE_ON_OR_AFTER" ]]` is a **string** comparison
  (ISO-8601 dates sort lexicographically in the same order as
  chronologically, which is exactly why `YYYY-MM-DD` is a good date format
  for scripts). `exec` replaces the current process with the Python one
  instead of spawning a child — a minor efficiency detail, but also means
  the script's exit code *is* the generator's exit code.

The self-disable line —
`systemctl --user disable --now cerberus-payments.timer` — is the wrapper
turning off its own trigger once the window closes. This is "self-retiring,
not self-deleting": nothing gets removed from disk, `generate_payments.py`
stays fully runnable by hand any time, only the *automatic* schedule stops.

---

## 4. Cloud Resources: AWS S3 fundamentals

Before reading the Terraform in §5, it helps to know what each S3 feature
being configured actually *does* — Terraform is just declaring these,
not inventing them.

| Feature | What it does | Why this project uses it |
|---|---|---|
| **Versioning** | Every `PUT` to the same key creates a new version instead of overwriting; a `DELETE` adds a "delete marker" instead of erasing data. | Backstop against accidental overwrite/delete — not the primary reliability mechanism (that's bronze's append-only *convention*), but a safety net under it. |
| **Server-side encryption (SSE-S3 / AES256)** | AWS encrypts every object at rest with keys it manages entirely; you never handle key material. | Baseline encryption-at-rest with zero operational overhead — the simplest of S3's three SSE modes (the others, SSE-KMS and SSE-C, add key-management complexity this project doesn't need). |
| **Public access block** | Four independent switches that override *any* bucket policy or ACL that would make objects public, even a future misconfigured one. | Defense in depth: even if someone later writes a broken bucket policy, this blocks the public-exposure failure mode outright. |
| **Ownership controls: `BucketOwnerEnforced`** | Disables S3 ACLs entirely; the bucket owner (this AWS account) owns every object unconditionally, no per-object ACL negotiation. | Simplifies the access model to "IAM policies only" — one fewer permission system to reason about. |
| **Lifecycle transition (Standard-IA)** | A background rule that automatically moves objects to a cheaper storage class after N days, based on age. | Cost control: aged bronze data is rarely re-read, so it doesn't need to sit on the most expensive storage tier. Standard-IA costs less per GB at the price of a small per-request retrieval fee. |

These five features map one-to-one to the five Terraform resource types
you'll see for every bucket in §5.4 (`aws_s3_bucket`,
`aws_s3_bucket_versioning`,
`aws_s3_bucket_server_side_encryption_configuration`,
`aws_s3_bucket_public_access_block`, `aws_s3_bucket_ownership_controls`) —
plus a sixth, `aws_s3_bucket_lifecycle_configuration`, for bronze only.

**Why five separate resource types for "one bucket"?** Older versions of
the AWS Terraform provider let you configure most of this as nested blocks
inside a single `aws_s3_bucket` resource. The provider deprecated that
around v4 in favor of one resource per S3 subsystem. It's more verbose, but
it mirrors the underlying S3 API more directly — each of these is a
genuinely separate API call (`PutBucketVersioning`,
`PutBucketEncryption`, `PutPublicAccessBlock`, ...), and Terraform's
resource model is now a more faithful 1:1 map to that API surface.

---

## 5. Infrastructure as Code: Terraform

### 5.1 Theory: what IaC actually buys you

**Infrastructure as Code** means describing the *desired end state* of
infrastructure in a file, and letting a tool compute and apply the
difference between that description and reality — rather than running
imperative commands (`aws s3 mb ...`) by hand and hoping you remember what
you did.

Terraform's model has three phases, every time:

1. **`terraform init`** — download the provider plugin (the code that
   knows how to talk to a specific API, here `hashicorp/aws`) and
   initialize the backend (where state lives — see §5.6).
2. **`terraform plan`** — read the current real-world state (by calling the
   provider's "describe" APIs), compare it against what the `.tf` files
   declare, and print a diff: what would be created, changed, or destroyed.
   **Nothing is touched yet.**
3. **`terraform apply`** — actually perform the plan's diff against real
   infrastructure.

This is **declarative**, not imperative: you write "there should be a
bucket named X with versioning enabled," not "run these six CLI commands
in this order." Terraform figures out the six commands (and their order,
via a dependency graph) itself. This also gives you **idempotency** — you
can run `terraform apply` a hundred times, and after the first one, every
subsequent run does nothing (`0 to add, 0 to change, 0 to destroy`), because
reality already matches the description. We verified this today: after
applying, a fresh `terraform plan` printed "No changes."

### 5.2 Project structure: modules vs. root modules

This project splits Terraform code into two layers, a very common pattern:

```
terraform/
├── bootstrap/            # (empty — Phase 1.5) will manage the state backend itself
├── modules/
│   └── s3_medallion/     # reusable, parameterized — describes HOW to build the bucket topology
└── envs/
    └── dev/              # a root module — describes WHICH instance to build, with what inputs
```

A **module** is just a directory containing `.tf` files. Every Terraform
directory is technically "a module" — the distinction between a **root
module** (`envs/dev/`, the one you actually run commands in) and a
**child/reusable module** (`modules/s3_medallion/`, referenced *from* a
root module) is purely about how it's used, not a different kind of file.
The reusable module knows nothing about "dev" — it just takes an
`account_id` and builds three buckets. That's what makes it reusable: a
future `envs/prod/` could call the same module with different inputs
without duplicating a single resource block.

### 5.3 HCL syntax primer

Terraform's language is **HCL** (HashiCorp Configuration Language). The
building blocks used throughout this project:

| Block type | Purpose | Example from this project |
|---|---|---|
| `resource "<type>" "<name>" { ... }` | Declares one real infrastructure object to manage. | `resource "aws_s3_bucket" "this" { ... }` |
| `variable "<name>" { ... }` | Declares an input parameter for the current module. | `variable "account_id" { type = string }` |
| `output "<name>" { ... }` | Exposes a value from the current module to whatever calls it. | `output "bucket_names" { value = ... }` |
| `locals { ... }` | Declares internal, computed values — not inputs, not resources, just named expressions for reuse within the module. | `locals { layers = { bronze = {...}, ... } }` |
| `data "<type>" "<name>" { ... }` | Reads information about something that already exists, without managing it. | `data "aws_caller_identity" "current" {}` |
| `module "<name>" { source = ...; ... }` | Instantiates a reusable module, passing it input variables. | `module "s3_medallion" { source = "../../modules/s3_medallion" ... }` |
| `provider "<name>" { ... }` | Configures how Terraform authenticates to and targets a specific API (region, credentials). | `provider "aws" { region = "us-east-1" ... }` |
| `terraform { ... }` | Meta-configuration: required Terraform version, required providers, backend. | see §5.6 |

### 5.4 Deep dive: the `s3_medallion` module

**`terraform/modules/s3_medallion/variables.tf`** — the module's inputs:

```hcl
variable "account_id" {
  description = "AWS account ID, used to build the cerberus-platform-<layer>-<account-id> bucket names."
  type        = string
}

variable "bronze_ia_transition_days" {
  description = "Days before bronze objects transition to S3 Standard-IA (ADR 0002)."
  type        = number
  default     = 30
}
```

`account_id` has no `default` — it's a **required** input, the caller must
supply it. `bronze_ia_transition_days` has a `default`, so it's
**optional**, and exists specifically because ADR 0002 said the lifecycle
threshold should be "a Terraform variable... so it can be tuned later
without a new ADR." That sentence in the ADR is *why* this is a variable
and not a hardcoded `30` in the resource block.

**`terraform/modules/s3_medallion/main.tf`** — the resources:

```hcl
locals {
  layers = {
    bronze = {
      bucket_name      = "cerberus-platform-bronze-${var.account_id}"
      phase            = "0"
      enable_lifecycle = true
    }
    silver = {
      bucket_name      = "cerberus-platform-silver-${var.account_id}"
      phase            = "1"
      enable_lifecycle = false
    }
    gold = {
      bucket_name      = "cerberus-platform-gold-${var.account_id}"
      phase            = "1"
      enable_lifecycle = false
    }
  }
}
```

This `locals` block is a **map of maps**: the outer keys (`bronze`,
`silver`, `gold`) are the layer names; each value is itself a map of that
layer's specific settings. `${var.account_id}` is **string
interpolation** — HCL's `${...}` syntax substitutes an expression's value
into a string. `phase` differs per layer deliberately: bronze really was
built in Phase 0 (it's being *adopted*, not created, here), while
silver/gold are genuinely new in Phase 1 — so the tag has to reflect each
bucket's real history, not one blanket value.

```hcl
resource "aws_s3_bucket" "this" {
  for_each = local.layers

  bucket = each.value.bucket_name

  tags = {
    Layer = each.key
    Phase = each.value.phase
  }
}
```

**`for_each`** is the mechanism that turns one `resource` block into three
actual buckets. Without it, you'd write three nearly-identical `resource
"aws_s3_bucket" "bronze" { ... }`, `"silver" { ... }`, `"gold" { ... }`
blocks by hand — `for_each` collapses that into one block iterated over a
map. Inside the block, `each.key` is the current map key (`"bronze"`,
`"silver"`, `"gold"`) and `each.value` is that key's value (the settings
map). The resulting resource's **address** — how you refer to a specific
instance elsewhere in the code, in `terraform state`, or on the CLI — is
`aws_s3_bucket.this["bronze"]`, `aws_s3_bucket.this["silver"]`, etc. This
address format is exactly what shows up in every `terraform import`
command in §5.7.

The next four resources all follow the identical pattern — `for_each` over
the same `local.layers` map, each one configuring a different S3 subsystem
for the *same* set of buckets:

```hcl
resource "aws_s3_bucket_versioning" "this" {
  for_each = local.layers
  bucket   = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.layers
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = local.layers
  bucket   = aws_s3_bucket.this[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = local.layers
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
```

Notice every one of these references `aws_s3_bucket.this[each.key].id` —
**not** `local.layers[each.key].bucket_name`. This is important: it's a
reference to *another resource's computed attribute*, which is how
Terraform builds its dependency graph. Terraform reads that reference and
concludes "the bucket must be created before its versioning config can be
set" — without anyone writing an explicit `depends_on`. This is **implicit
dependency ordering**, one of Terraform's core mechanics: reference a
resource's attribute, and the ordering falls out automatically.

Last, the lifecycle rule — the one resource that *doesn't* apply to all
three layers:

```hcl
resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  for_each = { for k, v in local.layers : k => v if v.enable_lifecycle }

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"
    filter {}
    transition {
      days          = var.bronze_ia_transition_days
      storage_class = "STANDARD_IA"
    }
  }
}
```

`{ for k, v in local.layers : k => v if v.enable_lifecycle }` is a **map
`for` expression with a filter** — it walks `local.layers` and keeps only
the entries where `enable_lifecycle` is `true`. Since only bronze has
`enable_lifecycle = true`, this expression evaluates to a one-entry map
(`{ bronze = {...} }`), so `for_each` over it produces exactly one
resource instance: `aws_s3_bucket_lifecycle_configuration.bronze["bronze"]`.
This is the idiomatic Terraform way to say "this resource applies
conditionally" — there's no `if` statement on a resource block itself;
you filter the collection you're iterating over instead.

**`terraform/modules/s3_medallion/outputs.tf`** — what this module exposes
to its caller:

```hcl
output "bucket_names" {
  description = "Map of layer -> bucket name."
  value       = { for k, v in aws_s3_bucket.this : k => v.bucket }
}

output "bucket_arns" {
  description = "Map of layer -> bucket ARN."
  value       = { for k, v in aws_s3_bucket.this : k => v.arn }
}
```

Another `for` expression, this time over a **resource** (`aws_s3_bucket.this`
is itself a map, because it was declared with `for_each`) rather than a
plain map — same syntax, different source collection. These two outputs
are what 1.6 (the IAM module, not yet built) will need: bucket ARNs to
scope IAM policies to specific buckets, per-layer.

### 5.5 Deep dive: the `envs/dev` root module

**`terraform/envs/dev/versions.tf`** — meta-configuration:

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "cerberus-platform-tfstate-131715059025"
    key            = "envs/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "cerberus-platform-tfstate-lock"
    encrypt        = true
    profile        = "cerberus-admin"
  }
}
```

- `required_version`/`required_providers` are guardrails: if someone runs
  this with an incompatible Terraform version or the wrong provider major
  version, it fails fast at `init` rather than producing confusing errors
  mid-`plan`. `~> 5.0` means "any 5.x, but not 6.0" — a common convention
  for pinning to a major version while accepting patch/minor updates.
- The `backend "s3"` block is covered in full in §5.6 below — it's the
  single most important block in this file for understanding how Terraform
  actually works as a *team* tool, not just a single-user script.

**`terraform/envs/dev/provider.tf`**:

```hcl
provider "aws" {
  region  = "us-east-1"
  profile = "cerberus-admin"

  default_tags {
    tags = {
      Project = "cerberus-platform"
    }
  }
}

data "aws_caller_identity" "current" {}
```

`default_tags` is a provider-level feature: every taggable resource this
provider manages automatically gets `Project = cerberus-platform` merged
into its tags, without repeating that key in every single `resource`
block. That's why `s3_medallion/main.tf`'s bucket resources only set
`Layer` and `Phase` in their own `tags` block — `Project` arrives for free
from the provider. (You can see this in the `tags_all` computed attribute
Terraform showed in the plan output — `tags_all` is the *merged* result of
a resource's own `tags` plus the provider's `default_tags`.)

`data "aws_caller_identity" "current" {}` is a **data source** — it makes a
read-only API call (`sts:GetCallerIdentity`) to ask AWS "who am I,"
returning the AWS account ID among other fields, *without* creating or
managing anything. This is what supplies `account_id` to the module below,
instead of hardcoding the literal `131715059025` anywhere in the `.tf`
files — a small but real IaC principle: derive values that are knowable
from the environment rather than hand-copying them.

**`terraform/envs/dev/main.tf`** — the entire root module's actual
resource declaration is three lines, because all the real work is in the
child module:

```hcl
module "s3_medallion" {
  source = "../../modules/s3_medallion"

  account_id = data.aws_caller_identity.current.account_id
}
```

`source` is a relative filesystem path here (modules can also come from a
Git URL or the public Terraform Registry — not needed for a project this
size). `account_id = data.aws_caller_identity.current.account_id` wires
the data source's result into the module's required input.

**`terraform/envs/dev/outputs.tf`** just re-exposes the module's outputs at
the root level, so `terraform output` at the top of `envs/dev/` shows
them directly:

```hcl
output "bucket_names" {
  value = module.s3_medallion.bucket_names
}
output "bucket_arns" {
  value = module.s3_medallion.bucket_arns
}
```

### 5.6 State management: the backend, and why it matters

**Terraform state** is a JSON file that records, for every resource
Terraform manages, the mapping between "the resource address in your `.tf`
files" (e.g. `module.s3_medallion.aws_s3_bucket.this["bronze"]`) and "the
real-world object it corresponds to" (the actual bucket, identified by
name/ARN), plus a cached copy of that object's last-known attributes. This
is *how* `terraform plan` can diff "declared" against "real" quickly — it
doesn't have to guess which real object corresponds to which resource
block.

State can live **locally** (a `terraform.tfstate` file on disk — fine for
solo experiments, dangerous for anything else: no locking, easy to lose,
impossible to share) or **remotely**, via a **backend**. This project uses
the **S3 backend**:

```hcl
backend "s3" {
  bucket         = "cerberus-platform-tfstate-131715059025"
  key            = "envs/dev/terraform.tfstate"
  region         = "us-east-1"
  dynamodb_table = "cerberus-platform-tfstate-lock"
  encrypt        = true
  profile        = "cerberus-admin"
}
```

- `bucket`/`key` — the state file itself lives as one object in S3, at
  `s3://cerberus-platform-tfstate-131715059025/envs/dev/terraform.tfstate`.
  Different environments (`envs/dev`, a hypothetical future `envs/prod`)
  use different `key`s in the *same* bucket, keeping their state
  completely separate.
- `dynamodb_table` — **state locking**. Before any `plan` or `apply`,
  Terraform writes a lock record into this DynamoDB table; if a second
  `terraform apply` starts while one is already running, it blocks instead
  of racing the first one and corrupting state. This is the exact
  DynamoDB table hand-created in Phase 0
  (`cerberus-platform-tfstate-lock`) — today's work is the first time
  anything actually *used* it.
- `encrypt = true` — the state file is encrypted at rest in S3. This
  matters more than it might look: Terraform state can contain sensitive
  values (though nothing sensitive exists in this project's state today).

Both the S3 bucket and DynamoDB table already existed, hand-created in
Phase 0 — this backend block is *pointing at* them, not creating them.
Managing those two resources themselves as Terraform code is explicitly
deferred to subtask 1.5, next up.

### 5.7 `terraform import`: adopting existing infrastructure

Every resource in Terraform's world starts in one of two ways: **created
by Terraform** (a plain `apply` with no prior state entry), or **imported**
— telling Terraform "this resource block corresponds to an object that
already exists in the real world; go read its current attributes into
state instead of creating a new one."

The bronze bucket was hand-created in Phase 0, before Terraform was ever
introduced to this project. ADR 0002 explicitly decided it should be
*adopted*, not recreated — recreating it would mean deleting and
re-creating a bucket that already holds real ingested data. So the
workflow for bronze specifically was: write the resource blocks first
(§5.4), then import each of bronze's five resources one at a time:

```bash
terraform import 'module.s3_medallion.aws_s3_bucket.this["bronze"]' \
  cerberus-platform-bronze-131715059025

terraform import 'module.s3_medallion.aws_s3_bucket_versioning.this["bronze"]' \
  cerberus-platform-bronze-131715059025

terraform import 'module.s3_medallion.aws_s3_bucket_server_side_encryption_configuration.this["bronze"]' \
  cerberus-platform-bronze-131715059025

terraform import 'module.s3_medallion.aws_s3_bucket_public_access_block.this["bronze"]' \
  cerberus-platform-bronze-131715059025

terraform import 'module.s3_medallion.aws_s3_bucket_ownership_controls.this["bronze"]' \
  cerberus-platform-bronze-131715059025
```

Each `terraform import <resource-address> <import-id>` takes two things: the
**resource address** (matching exactly the `for_each`-generated address
from §5.4 — this is why understanding that addressing scheme mattered) and
an **import ID**, whose format is provider- and resource-type-specific
(documented per resource in the AWS provider docs — for every S3
sub-resource used here, it happens to just be the bucket name).

**Silver and gold needed no import** — they didn't exist yet, so a normal
`apply` created them outright. **Only bronze**, the one pre-existing
resource, needed this adoption step. This is exactly the distinction ADR
0002 called out: "adopted via `terraform import`... not recreated."

**Verifying the import was clean.** Import only populates state — it
doesn't confirm your `.tf` code's declared attributes actually *match*
the real object. That's what `plan` is for immediately after: if the
`.tf` file had declared, say, `sse_algorithm = "aws:kms"` while the real
bucket used `AES256`, `plan` would show a *change* to bring reality in
line with the (wrong) declaration — a subtle way to accidentally mutate
existing infrastructure right after import. Today's `plan` came back
**11 to add, 0 to change, 0 to destroy** — the "0 to change" is the
important number: it confirms the hand-written `aws_s3_bucket_versioning`,
`..._encryption`, etc. blocks describe bronze's *actual* configuration
exactly (verified beforehand by reading it with `aws s3api
get-bucket-versioning` etc. — see §4's table for what each of those calls
was checking).

### 5.8 The apply

With the plan confirmed clean, `terraform apply` executed it — creating
11 new resources (silver + gold buckets and their four sub-resources each,
plus bronze's new lifecycle rule) and changing nothing on the imported
bronze resources. Verified afterward two ways: directly via
`aws s3api get-bucket-lifecycle-configuration` /
`get-bucket-versioning` / `get-public-access-block` against the new
buckets, and via a second `terraform plan`, which printed:

```
No changes. Your infrastructure matches the configuration.
```

That line is the practical definition of **idempotency** in action — the
same `.tf` files, run again, do nothing, because the described state and
the real state now agree.

---

## 6. Tooling decisions: Terraform vs. OpenTofu

**OpenTofu** is a fork of Terraform, created after HashiCorp changed
Terraform's license (BUSL 1.1) in 2023. It's a drop-in CLI replacement —
the HCL language is identical, so `.tf` files don't care which tool reads
them. This project's `Makefile` was deliberately built with a swappable
`TF_BIN` variable (`make dev-plan TF_BIN=tofu`) specifically to keep that
option open.

Work on 1.4 started with `tofu` (already installed) before switching to
real `terraform` mid-task, at explicit request — the goal here is building
Terraform-specific muscle memory, having just finished a beginner course,
so practicing on the tool that's actually being learned matters more than
which one happens to be pre-installed.

**Installing Terraform** used HashiCorp's official apt repository (Ubuntu
24.04 / "noble"):

```bash
wget -O- https://apt.releases.hashicorp.com/gpg | \
  sudo gpg --yes --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
  https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt update && sudo apt install terraform
```

**The one real gotcha:** switching tools mid-task turned out not to be
purely cosmetic. The bronze imports (§5.7) had already been run once with
`tofu import`, and **OpenTofu defaults to `registry.opentofu.org` as the
implicit provider registry**, while Terraform defaults to
`registry.terraform.io` — different hostnames, same underlying `aws`
provider code, but Terraform's state format records *which* one a
resource is bound to. That mismatch would have caused `terraform plan` to
treat the OpenTofu-imported resources as tracked by a provider it wasn't
configured to use.

The fix used one more piece of Terraform theory: state can be edited
independently of real infrastructure, because it's just Terraform's
bookkeeping, not the infrastructure itself.

```bash
terraform state rm \
  'module.s3_medallion.aws_s3_bucket.this["bronze"]' \
  'module.s3_medallion.aws_s3_bucket_ownership_controls.this["bronze"]' \
  'module.s3_medallion.aws_s3_bucket_public_access_block.this["bronze"]' \
  'module.s3_medallion.aws_s3_bucket_server_side_encryption_configuration.this["bronze"]' \
  'module.s3_medallion.aws_s3_bucket_versioning.this["bronze"]'
```

`terraform state rm` deletes entries **from state only** — it does not
touch, delete, or modify the real AWS resource in any way. It just makes
Terraform "forget" that it's tracking that resource. The five bronze
imports were then simply re-run with `terraform import` instead of `tofu
import`, and a `terraform state pull | grep provider` confirmed every
resource in state now uniformly referenced
`registry.terraform.io/hashicorp/aws`.

**What didn't change:** the Makefile's `TF_BIN` swappability, and the
OpenTofu mentions in README.md/architecture.md/plan.md — those stay, as a
deliberate decision to keep the *documented* flexibility even while the
*hands-on* tool for actually learning is Terraform specifically.

---

## 7. Glossary

| Term | Definition |
|---|---|
| **ADR** | Architecture Decision Record — a short document capturing one decision's context, choice, and consequences. |
| **HCL** | HashiCorp Configuration Language — the syntax Terraform (and OpenTofu) configuration files are written in. |
| **Provider** | A plugin that knows how to talk to a specific API (e.g. `hashicorp/aws` talks to AWS). Declared in `required_providers`, configured in a `provider` block. |
| **Resource** | One managed infrastructure object, declared with `resource "<type>" "<name>" { ... }`. |
| **Module** | A directory of `.tf` files. Every Terraform config is technically a module; "root module" = where you run commands, "child module" = one referenced via a `module` block. |
| **State** | Terraform's record of which resource blocks map to which real-world objects, plus their last-known attributes. |
| **Backend** | Where state is stored — local file, or remote (this project: S3 + DynamoDB lock). |
| **State locking** | A mechanism (here, a DynamoDB record) preventing two concurrent `apply`s from racing and corrupting state. |
| **`for_each`** | A meta-argument that turns one `resource`/`module` block into N instances, one per key in a map (or set). |
| **`locals`** | Named, computed values internal to a module — not inputs (`variable`), not outputs, just reusable expressions. |
| **`data` source** | A read-only lookup of something that already exists, without Terraform managing it. |
| **`terraform plan`** | Computes and prints the diff between declared and real state, without applying it. |
| **`terraform apply`** | Executes a plan's diff against real infrastructure. |
| **`terraform import`** | Binds an existing real-world object to a resource address in state, without creating anything. |
| **Idempotency** | Running the same operation repeatedly produces the same end state — a second `apply` after a clean one does nothing. |
| **Declarative** (vs. imperative) | Describing the desired *end state*, letting the tool compute the steps — as opposed to scripting the steps yourself. |
