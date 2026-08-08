# Day 02 — State Backends, IAM Roles, and the Glue Data Catalog

_Date: 2026-08-08 · Project: cerberus-platform · Phase: 1 — MVP: end-to-end
lakehouse_

**Purpose of this document.** Same as [day-01](day-01.md): a study note, not
a status report — [checkpoint.md](../../checkpoint.md) already tracks that.
The goal is capturing the *theory* behind each piece of code written today,
with the actual code inline, organized by discipline rather than the order
things happened in. Read it top to bottom once, then use it as a reference
later. Terms already defined in day-01's glossary (ADR, HCL, provider,
resource, module, state, backend, `for_each`, `locals`, data source,
`terraform plan`/`apply`/`import`, idempotency, declarative) aren't repeated
here even where they recur.

## Table of contents

1. [Infrastructure as Code: the Terraform bootstrap pattern](#1-infrastructure-as-code-the-terraform-bootstrap-pattern)
2. [Cloud Security: IAM roles, trust policies, and least privilege](#2-cloud-security-iam-roles-trust-policies-and-least-privilege)
3. [Data Engineering: the bronze → silver → gold transform](#3-data-engineering-the-bronze--silver--gold-transform)
4. [Cloud Resources: the AWS Glue Data Catalog](#4-cloud-resources-the-aws-glue-data-catalog)
5. [Glossary](#5-glossary)

---

## 1. Infrastructure as Code: the Terraform bootstrap pattern

### Theory

Every Terraform config needs somewhere to put its state (day-01, §5.6). This
project's state lives in an S3 bucket plus a DynamoDB lock table — but
those two resources were hand-built in Phase 0, and subtask 1.5 was to
bring *them* under Terraform too. That creates a genuine paradox: to manage
a resource with Terraform, that resource's config normally points its
`backend "s3" {}` block at *some* S3 bucket to store its state — but the
bucket being described here **is** the only state bucket this project has.
Pointing `terraform/bootstrap/`'s own state at
`cerberus-platform-tfstate-...` would mean the bucket's Terraform state
lives inside the bucket that state describes — recoverable in theory, but
fragile: a mistake while modifying the bucket could corrupt the very state
needed to fix it.

The standard resolution, used by essentially every real-world Terraform
setup that manages its own backend: carve out **one exception**. The
directory that manages the backend resources uses **local state** (a plain
`terraform.tfstate` file on disk) instead of the S3 backend everything else
uses. It's a small, deliberately narrow blast radius — this directory is
touched rarely, once the backend exists — in exchange for not needing to
solve a genuinely circular dependency.

### The code

`terraform/bootstrap/versions.tf` — note what's *absent*:

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately no `backend "s3" {}` block here. These resources ARE the
  # remote backend every other Terraform config (envs/dev, and future
  # envs/*) points at -- state for this directory can't live in the thing
  # it's describing. This is the standard Terraform bootstrap pattern:
  # state stays local (terraform.tfstate, gitignored) for this one
  # directory only, precisely because it has no chicken to its egg.
}
```

No `backend` block at all means Terraform falls back to its default: a
local `terraform.tfstate` file, written directly into
`terraform/bootstrap/` and already covered by `.gitignore`'s `*.tfstate`
pattern — it never gets committed.

`terraform/bootstrap/main.tf` declares the two resources exactly matching
what already existed (verified first via `aws s3api get-bucket-versioning`
etc. and `aws dynamodb describe-table`, the same discipline as 1.4's bronze
import):

```hcl
resource "aws_s3_bucket" "tfstate" {
  bucket = "cerberus-platform-tfstate-131715059025"

  tags = {
    Purpose = "terraform-state"
    Phase   = "0"
  }
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "cerberus-platform-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Purpose = "terraform-lock"
    Phase   = "0"
  }
}
```

`billing_mode = "PAY_PER_REQUEST"` is DynamoDB's on-demand mode — no
provisioned read/write capacity to size or pay for regardless of usage,
appropriate for a lock table that gets hit for a handful of requests per
`plan`/`apply`, not a steady workload. `hash_key = "LockID"` matches the
specific attribute name Terraform's S3 backend always uses when writing
lock records — this isn't an arbitrary column name, it's a contract the S3
backend expects.

Both resources (plus the S3 bucket's versioning, encryption,
public-access-block, and ownership-controls sub-resources — five S3
resources total, same pattern as day-01 §5.4) were imported, then planned:

```
Plan: 0 to add, 0 to change, 0 to destroy.
```

Zero to add — unlike 1.4, where silver and gold still needed creating,
*everything* here already existed exactly as declared. No `apply` step was
even necessary.

### New Terraform patterns this session

Two HCL mechanics showed up for the first time today, both in service of
wiring four modules together (`s3_medallion`, `glue_catalog`, `iam`, plus
the root `envs/dev` module itself):

**Cross-module wiring** — a module's output becomes another module's input,
chained:

```hcl
module "s3_medallion" {
  source     = "../../modules/s3_medallion"
  account_id = data.aws_caller_identity.current.account_id
}

module "glue_catalog" {
  source = "../../modules/glue_catalog"

  silver_bucket_name = module.s3_medallion.bucket_names["silver"]
  gold_bucket_name   = module.s3_medallion.bucket_names["gold"]
}

module "iam" {
  source = "../../modules/iam"

  bucket_arns           = module.s3_medallion.bucket_arns
  trusted_principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/cerberus-admin"

  account_id                = data.aws_caller_identity.current.account_id
  glue_database_name        = module.glue_catalog.database_name
  glue_table_names          = values(module.glue_catalog.table_names)
  glue_partition_table_name = module.glue_catalog.table_names["payments_events"]
}
```

Terraform reads these references (`module.s3_medallion.bucket_names[...]`,
`module.glue_catalog.database_name`) and builds a dependency graph from
them automatically — `iam` won't be planned until `glue_catalog` and
`s3_medallion` have resolved, the same implicit-ordering mechanic day-01
§5.4 covered for individual resources, just one level up at the module
level. `values(module.glue_catalog.table_names)` is a built-in function
that turns a map (`{payments_events = "payments_events", payments_current =
"payments_current"}`) into a plain list of its values — needed here because
`glue_table_names` expects `list(string)`, not a map.

**Dynamic blocks** — generating a variable number of repeatable nested
blocks from a collection, used in the Glue table resource (full context in
§4):

```hcl
dynamic "columns" {
  for_each = local.payment_columns
  content {
    name = columns.value.name
    type = columns.value.type
  }
}
```

Some HCL nested structures are ordinary list-typed *arguments*
(`tags = {...}`), but others — like `aws_glue_catalog_table`'s
`storage_descriptor { columns { ... } }` — are repeatable *blocks*, and
blocks can't be built from a `for` expression the way a list argument can.
`dynamic "<block_name>"` is the escape hatch: it iterates
`local.payment_columns` (a list of 15 `{name, type}` objects) and emits one
`columns { ... }` block per entry, with `columns.value` referring to the
current iteration's object inside `content`. Fifteen near-identical blocks,
one written by hand.

---

## 2. Cloud Security: IAM roles, trust policies, and least privilege

### Theory

An **IAM user** (like `cerberus-admin`) has long-lived credentials — an
access key that works until someone rotates or deletes it. An **IAM role**
has no credentials of its own at all. Instead, some already-authenticated
principal *assumes* it via the `sts:AssumeRole` API call, and in exchange
gets back **temporary** credentials (an access key, secret key, and session
token, expiring by default after an hour) scoped to exactly that role's
permissions — nothing more than what the role's own policy grants,
regardless of how privileged the original caller was.

A role has two policies doing two different jobs:

- **Trust policy** (`assume_role_policy` in Terraform) — *who* is allowed
  to assume this role. Answers "can you even ask for these credentials?"
- **Permission policy** — *what* the role can do once assumed. Answers
  "now that you're wearing this identity, what are you allowed to touch?"

**Least privilege** means each identity gets exactly the permissions it
needs and nothing else — not because it's tidy, but because it shrinks the
blast radius of any single compromised credential or buggy script. A script
running as `cerberus-admin` that has a bug can touch *anything* in the
account; the same bug in a script running as `cerberus-ingestion` can, at
worst, write files under `bronze/payments/`.

### The code

`terraform/modules/iam/main.tf` — one trust policy shape, reused by all
three roles, parameterized only by who's trusted:

```hcl
locals {
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = var.trusted_principal_arn }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}
```

`jsonencode(...)` takes an HCL object literal and serializes it to a JSON
string at plan time — AWS IAM policies are JSON documents regardless of
which tool writes them, and this is how Terraform constructs one from
ordinary HCL values instead of a hand-typed JSON string (which would lose
type-checking and interpolation).

The simplest permission policy, `cerberus-ingestion`:

```hcl
resource "aws_iam_role_policy" "ingestion" {
  name = "cerberus-ingestion-policy"
  role = aws_iam_role.ingestion.id

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

One action, one resource pattern. Nothing else — this role cannot read,
list, or delete anything, anywhere.

`cerberus-transform`'s policy is where the resource-ARN mechanics get more
interesting:

```hcl
{
  Sid      = "ListBronzePaymentsPrefixOnly"
  Effect   = "Allow"
  Action   = "s3:ListBucket"
  Resource = var.bucket_arns["bronze"]
  Condition = {
    StringLike = { "s3:prefix" = ["payments/*"] }
  }
}
```

This is a subtlety worth understanding on its own: `s3:GetObject` and
`s3:PutObject` are **object-level** actions, so they take an
**object-level** ARN — `bucket-arn/key-pattern`, e.g.
`.../bronze-bucket/payments/*`. But `s3:ListBucket` is a **bucket-level**
action (you're asking "what's in this bucket," not "give me this specific
object"), so its `Resource` must be the **bucket ARN alone**, with no key
suffix. That means a plain bucket-ARN grant of `ListBucket` would let the
role list *everything* in bronze, including anything outside `payments/` —
so restricting it to a prefix requires a `Condition` block matching the
`s3:prefix` value the caller's `ListObjectsV2` request actually sends. This
is the only way to scope a bucket-level action to a subset of the bucket;
there's no ARN wildcard trick that does it directly.

**Manually verified, not just declared.** After `apply`, the ingestion
role was actually assumed and exercised, to prove the policy really
enforces what it claims rather than trusting the JSON on faith:

```bash
CREDS=$(aws sts assume-role \
  --role-arn arn:aws:iam::131715059025:role/cerberus-ingestion \
  --role-session-name test-ingestion \
  --profile cerberus-admin --region us-east-1 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...

aws s3 cp test.json s3://cerberus-platform-bronze-.../payments/dt=.../x.json
# succeeds

aws s3 cp test.json s3://cerberus-platform-bronze-.../not-payments/x.json
# AccessDenied: not authorized to perform s3:PutObject on that resource

aws s3 ls s3://cerberus-platform-bronze-.../payments/
# AccessDenied: not authorized to perform s3:ListBucket
# (ingestion's policy has no ListBucket statement at all)

aws s3 cp s3://cerberus-platform-gold-.../anything.json .
# 403 Forbidden — ingestion has no gold access whatsoever
```

All four outcomes matched the policy exactly: this is what "verified, not
just declared" means in practice — a policy JSON that *looks* right and a
policy that *behaves* right are different claims, and only testing the
second one actually confirms it.

### Design decisions

**Real roles now, not bare policy documents.** Nothing in this pipeline is
Lambda or EKS yet (that's Phase 2/3) — there's no automated compute to
*assume* these roles today. The alternative was building just the three
`aws_iam_policy` documents, inert until future phases attach them to real
compute. Chose real, assumable roles instead: they're genuinely testable
today (as just shown), and they're a deliberate head start on repaying
Phase 0's `cerberus-admin` `AdministratorAccess` shortcut incrementally,
rather than leaving all of it to the dedicated least-privilege review at
7.3.

**Inline policies, not standalone managed policies.** Each role's policy
(`aws_iam_role_policy`) is declared directly attached to its role, rather
than as a separate `aws_iam_policy` resource plus an
`aws_iam_role_policy_attachment`. Standalone managed policies earn their
keep when a policy is shared across multiple roles or needs independent
versioning; here, each policy is scoped 1:1 to exactly one role and was
never going to be reused elsewhere, so the extra resource and attachment
step would have been indirection without benefit.

**Extended, not redesigned, once 1.8 needed Glue access.** `cerberus-serving`
was originally scoped "S3-only for now" with an explicit comment
anticipating Glue/Athena permissions would land once those subtasks were
built. When 1.8 arrived, that's exactly what happened — a new statement
appended to the existing policy, not a rewritten role:

```hcl
{
  Sid    = "ReadPaymentsCatalog"
  Effect = "Allow"
  Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
  Resource = concat(
    [local.glue_catalog_arn, local.glue_database_arn],
    local.glue_serving_table_arns,
  )
}
```

Glue's IAM model requires granting the **catalog**, **database**, and
**table** ARNs together for table-level read actions — a three-level
resource hierarchy (`arn:aws:glue:<region>:<account>:catalog`, `.../database/<db>`,
`.../table/<db>/<table>`), unlike S3's two-level bucket/object model above.
`concat(...)` merges the fixed two-element list (catalog, database) with
`glue_serving_table_arns` (one entry per table, built via a `for`
expression over `var.glue_table_names`) into one flat resource list.

---

## 3. Data Engineering: the bronze → silver → gold transform

### Theory

**Why Parquet, not JSON, from silver onward.** JSON is row-oriented: every
object is a self-contained blob, read top to bottom. **Parquet is
columnar** — all values for one column are stored together, physically
adjacent on disk. Two consequences fall out directly: a query that only
needs 3 of 15 columns can skip reading the other 12 entirely (**column
pruning**), and values of the same type sitting next to each other compress
far better than a JSON blob's mixed structure — which is why **Snappy**
compression (fast to (de)compress, moderate ratio, and critically
*splittable* — a big file can be processed in parallel chunks, unlike
gzip) pairs naturally with Parquet for analytical workloads. Bronze stays
raw JSON deliberately (day-01 §5.4's format tension); this is the layer
where that trade finally gets paid off.

**Latest-event-wins.** Bronze and silver both hold an *event log* — every
lifecycle step (`created`, `authorized`, `settled`, ...) is its own
immutable row, nothing is ever updated in place. But "what's this
transaction's status *right now*" is a completely reasonable question, and
nowhere does a single row answer it directly. The answer is **derived**:
group all of a transaction's events by `transaction_id`, and take whichever
one has the latest `event_timestamp`. This is the same pattern behind
event sourcing and change-data-capture systems generally — the log is the
source of truth, and "current state" is always a *computed view* over it,
never a separately maintained mutable field that could drift out of sync
with the log.

**Full rebuild vs. incremental.** Every run of this transform reprocesses
*all* of bronze from scratch, rather than tracking a watermark ("only
process objects newer than the last run"). At this project's data volume
(low thousands of events), the simplicity is worth far more than the
wasted recomputation: there's no watermark state to persist, corrupt, or
reason about, and the script is trivially idempotent — run it any number of
times, silver and gold always converge to the same answer.

### The code

**Assuming a role from application code**, the boto3 equivalent of the CLI
`sts assume-role` shown in §2:

```python
def assumed_session():
    base = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    sts = base.client("sts")
    creds = sts.assume_role(
        RoleArn=TRANSFORM_ROLE_ARN, RoleSessionName="promote-payments"
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=REGION,
    )
```

The `base` session (real `cerberus-admin` credentials, from the local AWS
CLI profile) exists only long enough to make one `sts:AssumeRole` call.
Every subsequent AWS call in this script goes through the **returned**
session instead, built from the role's temporary credentials — so if this
script has a bug, the damage is bounded by `cerberus-transform`'s policy,
not `cerberus-admin`'s.

**Flattening** nested JSON into flat rows a DataFrame can hold:

```python
def flatten(events):
    rows = []
    for e in events:
        merchant = e["merchant"]
        customer = e["customer"]
        pm = e["payment_method"]
        rows.append({
            "transaction_id": e["transaction_id"],
            "event_type": e["event_type"],
            "event_timestamp": e["event_timestamp"],
            "amount": e["amount"],
            "currency": e["currency"],
            "merchant_id": merchant["merchant_id"],
            "merchant_name": merchant["name"],
            "merchant_category": merchant["category"],
            "customer_id": customer["customer_id"],
            "customer_name": customer["name"],
            "customer_email": customer["email"],
            "payment_method_type": pm["type"],
            "payment_method_brand": pm.get("brand"),
            "payment_method_last4": pm.get("last4"),
            "payment_method_token": pm["token"],
        })
    df = pd.DataFrame(rows)
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True)
    return df
```

`pm.get("brand")` (not `pm["brand"]`) matters here: `bank_transfer` and
`wallet` payment methods (1.3's generator) never had a `brand` or `last4`
key at all, only `card` does. `.get()` returns `None` for the missing
cases, which pandas/pyarrow store as a proper nullable value in the
Parquet output rather than raising a `KeyError`.

**Writing Parquet straight to S3, no local file:**

```python
def write_parquet(s3, df, bucket, key):
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", compression="snappy", index=False)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
```

`io.BytesIO()` is an in-memory, file-like buffer — `to_parquet` writes to
it exactly as it would a real file on disk, but nothing ever touches the
filesystem. `put_object` then uploads the buffer's raw bytes directly.

**Silver: one file per day, deterministic key, latest-event-wins for
gold:**

```python
def write_silver(s3, df):
    df = df.copy()
    df["dt"] = df["event_timestamp"].dt.strftime("%Y-%m-%d")
    days = sorted(df["dt"].unique())
    for day, day_df in df.groupby("dt"):
        key = f"payments/dt={day}/events.parquet"
        write_parquet(s3, day_df.drop(columns="dt"), SILVER_BUCKET, key)
    return days

def write_gold(s3, df):
    latest = df.sort_values("event_timestamp").groupby("transaction_id").tail(1)
    write_parquet(s3, latest, GOLD_BUCKET, "payments_current/current_state.parquet")
```

`events.parquet` — a fixed filename, not one suffixed with a run timestamp
the way bronze's uploads are. That's deliberate: bronze is meant to
*accumulate* (append-only, every run adds new objects), but silver and
gold are *derived* — each rebuild should fully replace the previous one at
the same key, not pile up stale duplicates alongside the current data.
`sort_values("event_timestamp").groupby("transaction_id").tail(1)` is the
latest-event-wins theory made concrete: sort every event chronologically,
group by transaction, keep only the last row of each group.

**Result:** ran clean against all 37 bronze objects — 2,451 events,
9 silver day-partitions, gold resolved to 805 distinct transactions (729
settled / 40 failed / 36 refunded). Verified by reading both outputs back
with pandas: gold's row count matched its unique `transaction_id` count
exactly, confirming the dedup was correct, not just non-erroring.

---

## 4. Cloud Resources: the AWS Glue Data Catalog

### Theory

**The Glue Data Catalog is a metastore, not a database.** It stores table
*definitions* — schema, file format, and an S3 location — completely
separate from the data itself. Multiple engines (Athena, Spark, Redshift
Spectrum) can all read the same catalog entry and agree on what a "table"
means, without any of them owning the underlying files. This is exactly why
every table declared today is `table_type = "EXTERNAL_TABLE"`: an external
table is pure metadata pointing *at* data that lives and is managed
entirely outside Glue's control (here, by 1.7's transform). Dropping the
Glue table tomorrow would delete zero bytes of Parquet in S3 — only the
catalog entry describing it.

**SerDe** (Serializer/Deserializer) is the piece that knows how to turn a
file's raw bytes into rows and columns for a specific format — here,
`ParquetHiveSerDe` for reading Parquet. Different file formats (CSV, JSON,
ORC, Parquet) need different SerDes; the catalog entry has to name the
right one so query engines know how to decode what's actually in the
bucket.

**Partitions, and partition pruning.** A Hive-style partitioned table maps
physical subdirectories (`dt=2026-08-05/`) to a logical column (`dt`) in
the schema — but the *table definition* only says "this table has a
partition key called `dt`, type string." It says nothing about which
values of `dt` actually exist; that mapping — "`dt=2026-08-05` lives at
this S3 prefix" — has to be registered separately, per partition, or the
query engine won't know the partition exists at all. The entire point is
**partition pruning**: a query filtering `WHERE dt = '2026-08-05'` can skip
scanning every other day's data completely, at the metadata level, before
touching a single Parquet file — the same Cost Optimization lever day-01
§4 covered ("Athena bills per TB scanned").

### The code

`terraform/modules/glue_catalog/main.tf` — table + partition-key
declaration + the dynamic columns block from §1, combined:

```hcl
resource "aws_glue_catalog_table" "payments_events" {
  name          = "payments_events"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification  = "parquet"
    compressionType = "snappy"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.silver_bucket_name}/payments/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.payment_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
```

`gold`'s `payments_current` table is identical except for having **no**
`partition_keys` block at all — it's a single flat table (§3's
`current_state.parquet`), so there's nothing to partition by.

**Explicit schema, not a Crawler.** AWS Glue can auto-detect a table's
schema with a **Crawler** — a scheduled job that scans sample files and
infers columns/types. None was used here: this pipeline owns *both* ends
(the transform that writes the Parquet, and the catalog that describes it),
so the schema is already fully known with certainty. A Crawler earns its
keep when schema is unknown or evolves from an external, un-owned source;
paying to have AWS re-derive something already certain would be strictly
worse than declaring it — slower (crawl runs take time), costs money per
run, and isn't reviewable in a Terraform diff the way an explicit column
list is.

**Partitions are registered by the transform script, not Terraform.**
Terraform owns the table's *shape* (schema, partition key name, location) —
that changes rarely, essentially only when the pipeline's data model
changes. But the *set of partitions that exist* grows every single time the
transform runs, which makes it data, not infrastructure — trying to hold
that in a `.tf` file would mean re-running `terraform apply` as an
operational step every day, exactly backwards from what Terraform is for.
Instead, `promote_payments.py` registers each day partition directly via
the Glue API, using a column list kept in sync with the Terraform module by
hand (no shared schema source between HCL and Python today):

```python
def register_partitions(glue, days):
    partitions = [
        {
            "Values": [day],
            "StorageDescriptor": {
                "Location": f"s3://{SILVER_BUCKET}/payments/dt={day}/",
                "InputFormat": PARQUET_INPUT_FORMAT,
                "OutputFormat": PARQUET_OUTPUT_FORMAT,
                "SerdeInfo": {"SerializationLibrary": PARQUET_SERDE},
                "Columns": PARQUET_COLUMNS,
            },
        }
        for day in days
    ]
    resp = glue.batch_create_partition(
        DatabaseName=GLUE_DATABASE,
        TableName=GLUE_SILVER_TABLE,
        PartitionInputList=partitions,
    )
    errors = resp.get("Errors", [])
    for err in errors:
        if err["ErrorDetail"]["ErrorCode"] != "AlreadyExistsException":
            raise RuntimeError(f"Glue partition registration failed: {err}")
    new = len(days) - len(errors)
    print(f"[transform] registered {new} new Glue partition(s), {len(errors)} already existed")
```

`batch_create_partition` is a **batch** API — it returns an `Errors` list
for whichever partitions in the request failed, rather than raising on the
first failure. Treating `AlreadyExistsException` as expected (not an error)
is what makes re-running the transform safe: the second run of the day
tries to register the same 9 partitions again, gets 9
`AlreadyExistsException` entries back, and reports "0 new... 9 already
existed" instead of crashing — the same idempotency property §1 and §3
both lean on, applied to the catalog layer too.

**Verified via the Glue API directly**, not Athena (which isn't built yet —
that's 1.10):

```bash
aws glue get-table --database-name cerberus_platform --name payments_events \
  --query 'Table.{Location:StorageDescriptor.Location,PartitionKeys:PartitionKeys}'
# Location: s3://cerberus-platform-silver-.../payments/
# PartitionKeys: [{Name: dt, Type: string}]

aws glue get-partitions --database-name cerberus_platform --table-name payments_events \
  --query 'Partitions[].Values'
# all 9 dt= values present
```

---

## 5. Glossary

| Term | Definition |
|---|---|
| **Bootstrap pattern** | Managing a backend's own resources (state bucket, lock table) with local Terraform state, since they can't point their own backend config at themselves. |
| **Local state** | Terraform state stored as a plain file on disk rather than in a remote backend — the default when no `backend` block is configured. |
| **`dynamic` block** | HCL syntax for generating a variable number of repeatable nested blocks (as opposed to a list-typed argument) from a collection. |
| **IAM role** | An identity with no permanent credentials, assumed temporarily via `sts:AssumeRole` in exchange for short-lived, scoped credentials. |
| **Trust policy** | A role's policy defining *who* may assume it (the `Principal`). |
| **Permission policy** | A role's policy defining *what* it can do once assumed. |
| **`sts:AssumeRole`** | The STS API call that exchanges an allowed caller identity for temporary credentials scoped to a target role. |
| **Least privilege** | Granting each identity exactly the permissions it needs, nothing more — shrinks the blast radius of any single credential. |
| **Inline policy** | An IAM policy (`aws_iam_role_policy`) attached directly to one role, vs. a standalone managed policy meant to be shared/reused. |
| **Columnar storage** | A file layout (e.g. Parquet) storing all values of one column contiguously, enabling column pruning and better compression than row-based formats like JSON. |
| **Snappy compression** | A fast, splittable, moderate-ratio compression codec — pairs well with Parquet for parallel analytical processing. |
| **Latest-event-wins** | Deriving "current state" from an immutable event log by taking each entity's most recent event, rather than storing a separately mutable status field. |
| **Full rebuild** | Reprocessing an entire dataset from scratch every run, instead of tracking a watermark for incremental processing — simpler, trivially idempotent, at the cost of redundant compute. |
| **Glue Data Catalog** | AWS's managed Hive-compatible metastore: table schema, format, and location, decoupled from any specific query engine. |
| **External table** | A catalog table that is pure metadata pointing at externally-managed data — dropping the table doesn't delete the underlying files. |
| **SerDe** | Serializer/Deserializer — the component that decodes a specific file format's bytes into rows/columns (e.g. `ParquetHiveSerDe`). |
| **Partition (Hive-style)** | A physical subdirectory (`dt=YYYY-MM-DD/`) mapped to a logical partition-key column, registered separately from the table's schema. |
| **Partition pruning** | A query engine skipping entire partitions at the metadata level based on a filter, without scanning their data files. |
| **Glue Crawler** | An AWS-managed job that infers table schema by scanning sample files — unnecessary when the schema is already fully known and owned. |
