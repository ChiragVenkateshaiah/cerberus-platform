# Day 03 — Athena Serving, dbt Fact/Dimension Models & Live Infrastructure Verification

_Date: 2026-08-10 · Project: cerberus-platform · Phase: 1 — MVP: end-to-end
lakehouse (complete as of today)_

**Purpose of this document.** This is a study note, not a status report —
[checkpoint.md](../../checkpoint.md) already tracks that. The goal here is
to capture the *theory* behind each piece of code written today, with the
actual code inline, organized by discipline the way an engineering
curriculum would group it. Read it top to bottom once, then use it as a
reference later.

## Table of contents

1. [Cloud Resources: Amazon Athena fundamentals](#1-cloud-resources-amazon-athena-fundamentals)
2. [Cloud Security: role-chaining and empirically-discovered permissions](#2-cloud-security-role-chaining-and-empirically-discovered-permissions)
3. [Data Engineering: dbt and the fact/dimension split](#3-data-engineering-dbt-and-the-factdimension-split)
4. [Infrastructure as Code: verifying destroy and apply against live infrastructure](#4-infrastructure-as-code-verifying-destroy-and-apply-against-live-infrastructure)
5. [Governance: the AWS Well-Architected Tool](#5-governance-the-aws-well-architected-tool)
6. [Glossary](#6-glossary)

---

## 1. Cloud Resources: Amazon Athena fundamentals

### Theory

**Amazon Athena** is a serverless SQL query engine (built on Trino/Presto)
that runs standard SQL directly against files sitting in S3 — no cluster to
provision, size, or tear down. The critical mental model: **Athena stores
nothing itself.** It's compute, not storage. Every byte it touches comes
from two other things day-02 already introduced: the **Glue Data Catalog**
tells it *what* tables exist and *where* their files live; **S3** holds the
actual bytes, both what Athena reads and what it writes.

That "what it writes" part matters more than it first appears. Every query
— even a plain `SELECT` — needs somewhere in S3 to put its output. A
**workgroup** is Athena's resource-management boundary for a set of
queries: it can pin a default output location, enforce (or not enforce)
that location on every query run under it, publish CloudWatch metrics, and
cap `bytes_scanned_cutoff_per_query` — a real cost guardrail, not just
advisory, that fails a query outright if it would scan more than the
configured limit.

### The code

`terraform/modules/athena/main.tf` — the query-results bucket (transient,
lifecycle-**expired** rather than transitioned to IA like bronze, since
query output is disposable and always re-derivable) and the workgroup:

```hcl
resource "aws_athena_workgroup" "this" {
  name = "cerberus_platform"

  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = false
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff_bytes
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/"
    }
  }
}
```

**Why this matters — the `enforce_workgroup_configuration` gotcha.** The
first instinct is "enforce = safer, obviously turn it on." It was on
initially. The first `dbt run` succeeded, created three tables — and every
one of them physically landed under the query-results bucket's
`tables/<uuid>/` path instead of the gold bucket, silently. Reading
dbt-athena's actual materialization macro explained why: when it builds a
`CREATE TABLE ... AS SELECT` statement, it conditionally *omits* the
`external_location` clause whenever the target workgroup enforces its own
output location — to avoid the query rejecting a location that conflicts
with the workgroup's mandated one. With enforcement on, there was no way to
tell Athena "put this table's data in gold" — every dbt-managed table
silently fell back to the workgroup's default. Turning enforcement off
fixed it without losing the cost guardrail: `bytes_scanned_cutoff_per_query`
still applies as a default for any caller (dbt included) that doesn't
explicitly override it — only the *ability* to override is what enforcement
would have added, and nothing here needed that.

---

## 2. Cloud Security: role-chaining and empirically-discovered permissions

### Theory

Day-02 covered one way to assume an IAM role from a script: call
`sts:AssumeRole` explicitly in Python (`promote_payments.py`'s
`assumed_session()`). That works for code this project controls, but dbt
and the AWS CLI are tools it doesn't — there's no hook to inject a custom
assume-role call before they run. The alternative is an **AWS CLI named
profile using role chaining**: a profile that names a `role_arn` and a
`source_profile`, and lets `boto3`/the AWS CLI perform the assume-role
handshake transparently, every time that profile name is used, with no code
written for it at all.

```ini
[profile cerberus-transform]
role_arn = arn:aws:iam::131715059025:role/cerberus-transform
source_profile = cerberus-admin
region = us-east-1
```

Anything that reads AWS CLI profiles — `dbt`'s `aws_profile_name` config,
a plain `aws athena ...` command, `boto3.Session(profile_name=...)` — gets
temporary, scoped credentials for `cerberus-transform` without a single
line of STS code. A matching `cerberus-serving` profile does the same for
the read-only demo-query path.

The IAM policies those roles hold weren't fully known upfront — several
permissions were discovered the honest way, by running the real thing and
reading the exact `AccessDeniedException` it produced:

| Missing permission | Found by | Why it's needed |
|---|---|---|
| `s3:GetBucketLocation` | `dbt debug`'s connection check | Athena's `StartQueryExecution` "verifies" the output bucket exists before running, which requires this |
| `glue:GetDatabases` (plural) | first `dbt run` | dbt-athena lists all databases to check/create the target schema, not just get one by name |
| `s3:DeleteObject` (results + gold buckets) | second `dbt run` | Every CTAS run clears its target S3 location first — this happens on *every* run, not just `--full-refresh` |

Each of these is now a documented `Sid` in `terraform/modules/iam/main.tf`,
but none of them were predicted from reading dbt-athena's docs ahead of
time — they surfaced from actually exercising the path.

### The code

The permissions dbt needs to run and to create/manage the tables it owns —
scoped with a **wildcard ARN**, so `cerberus-transform` can `CreateTable`/
`DeleteTable` on tables *it* creates without touching `payments_events` or
`payments_current`, which stay Terraform's:

```hcl
locals {
  glue_dbt_fct_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/fct_*"
  glue_dbt_dim_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/dim_*"
}

# ManageDbtGoldTables statement (excerpt):
Action = [
  "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
  "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
  "glue:BatchCreatePartition", "glue:GetPartitions", "glue:BatchDeletePartition",
]
Resource = [
  local.glue_catalog_arn, local.glue_database_arn,
  local.glue_dbt_fct_table_arn, local.glue_dbt_dim_table_arn,
]
```

The `*` in an ARN string is ordinary IAM resource-matching syntax, not a
Glue-specific feature — it works here because table names in the catalog
happen to be structured (`fct_transactions`, `dim_merchants`, ...) in a way
that makes prefix-matching meaningful.

---

## 3. Data Engineering: dbt and the fact/dimension split

### Theory

**dbt** ("data build tool") lets you write a transformation as a plain SQL
`SELECT` statement — a **model** — and handles turning it into a real
table or view for you. It's built around two Jinja functions that
distinguish where data comes from:

- `{{ source(...) }}` — points at data dbt did **not** create (here,
  `payments_events`, 1.7's transform output, registered as a dbt **source**
  in `models/sources.yml` rather than built by a model).
- `{{ ref(...) }}` — points at another dbt model, letting dbt infer the
  dependency graph between models automatically. (Not used yet here, since
  all three marts read directly from the one source rather than from each
  other.)

A model's **materialization** controls what dbt actually does with the
`SELECT`'s result: `view` just wraps it as a saved query (cheap, always
fresh, re-executes every read); `table` runs it once and persists the
result as a real physical table. `table` was chosen here — a deliberate
echo of 1.7's own "full rebuild every run" design, not a different
philosophy:

```yaml
# dbt_project.yml
models:
  cerberus_platform:
    marts:
      +materialized: table
```

### The code

**Connection config** (`profiles.yml`) — committed to the repo rather than
kept in dbt's usual `~/.dbt/profiles.yml`, since every value in it is a
non-secret infrastructure identifier (credentials live in the
`cerberus-transform` AWS profile from §2, not here):

```yaml
cerberus_platform:
  target: dev
  outputs:
    dev:
      type: athena
      aws_profile_name: cerberus-transform
      s3_staging_dir: s3://cerberus-platform-athena-results-131715059025/dbt/
      s3_data_dir: s3://cerberus-platform-gold-131715059025/
      s3_data_naming: table
      work_group: cerberus_platform
      schema: cerberus_platform
      database: awsdatacatalog
```

**Why a fact/dimension split at all?** 1.7's `payments_current` is one
denormalized row per transaction, with merchant/customer detail embedded
inline. That's fine for a quick current-state view, but it repeats the same
merchant's name and category in every row that mentions them — ADR 0003
deliberately deferred fixing this to dbt. A **fact table** (one row per
business event, referencing other entities by ID) plus **dimension
tables** (one row per entity, deduplicated) is the standard normalization
this problem calls for.

`dim_merchants.sql` and `dim_customers.sql` are the easy half — the roster
never changes per event (ADR 0003), so there's no "current" value to
resolve, just distinct rows:

```sql
select distinct
    merchant_id,
    merchant_name,
    merchant_category
from {{ source('cerberus_platform', 'payments_events') }}
```

`fct_transactions.sql` is the harder half, because a transaction's
`status` genuinely does change across its event history — this needs the
same **latest-event-wins** resolution day-02's Python/pandas transform
used, just expressed in SQL via a **window function**:

```sql
with ranked as (
    select
        *,
        row_number() over (
            partition by transaction_id
            order by event_timestamp desc
        ) as rn
    from {{ source('cerberus_platform', 'payments_events') }}
)

select
    transaction_id, event_type as status, event_timestamp as last_event_at,
    amount, currency, merchant_id, customer_id,
    payment_method_type, payment_method_brand, payment_method_last4, payment_method_token
from ranked
where rn = 1
```

`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ... DESC)` assigns a rank
*within each group* — here, each group is one `transaction_id`'s full
event history, numbered `1, 2, 3, ...` starting from the most recent event
(`DESC`). Filtering to `rn = 1` keeps exactly one row per transaction: its
latest event. The result references `merchant_id`/`customer_id` as foreign
keys instead of embedding the merchant's name and category directly — the
normalization this whole exercise was for.

---

## 4. Infrastructure as Code: verifying destroy and apply against live infrastructure

### Theory

`terraform plan -destroy` shows what *would* be destroyed, but it's still
just a diff against state — it never calls a real Delete API, so it can't
surface runtime-only failures. Some things only break when you actually try
to delete them: an S3 bucket refuses to delete if it still holds objects
(including old, non-current versions if versioning is on — a plain
"delete current objects" pass isn't enough), and some resources expose a
**`force_destroy`** flag specifically to bypass an equivalent "must be
empty first" check on the provider's side.

### The code

Purging every object **version and delete marker** (not just current
objects) from a versioned bucket, since `terraform destroy` will otherwise
fail on "bucket not empty" even after a normal `aws s3 rm --recursive`:

```bash
RAW="$(aws s3api list-object-versions --bucket "$BUCKET" --profile "$PROFILE" --max-items 1000 --output json)"
OBJECTS="$(echo "$RAW" | jq '[(.Versions // [])[], (.DeleteMarkers // [])[] | {Key, VersionId}]')"
aws s3api delete-objects --bucket "$BUCKET" --profile "$PROFILE" --delete "{\"Objects\": $OBJECTS, \"Quiet\": true}"
```

**The gotcha worth knowing precisely.** Setting `force_destroy = true` in
the `.tf` file was not, by itself, enough — the first `terraform destroy`
still failed with `WorkGroup cerberus_platform is not empty`. The reason:
a destroy plan computes its actions from current **state**, and a resource
about to be deleted doesn't go through the normal "diff config against
state, update the attribute" logic a regular `apply` would — so the new
`force_destroy` value sitting in the `.tf` file was never actually written
into state, and the provider's delete call still saw the old value. The
fix was applying that one attribute into state first, deliberately scoped
with `-target` to avoid touching (or recreating) anything else:

```bash
terraform apply -auto-approve -target=module.athena.aws_athena_workgroup.this
terraform destroy -auto-approve   # now succeeds
```

A related discovery, this time a pleasant one: destroying the Glue
database (`aws_glue_catalog_database.this`) **cascade-deleted every table
inside it** — including `fct_transactions`, `dim_merchants`, and
`dim_customers`, none of which Terraform was tracking (dbt created them
directly via the Glue API). S3 buckets and Glue databases have opposite
default behaviors here: a bucket *refuses* to delete non-empty, a database
*doesn't* — worth knowing explicitly per-service rather than assuming one
model holds everywhere.

Both fixes verified for real, not just planned: `terraform destroy` (31
resources) followed by `terraform apply` rebuilding all 31 from nothing,
then bronze's backed-up data restored and the transform + dbt re-run to
reconstruct silver/gold/marts from scratch.

---

## 5. Governance: the AWS Well-Architected Tool

### Theory

The **AWS Well-Architected Tool** structures a self-review as a **workload**
(the thing being reviewed) evaluated against one or more **lenses** (a
question set — the default is the Framework lens, covering all six
pillars). Each pillar's questions offer a list of best-practice **choices**;
selecting the ones that genuinely apply — or explicitly marking a question
not applicable, with a reason — produces a computed **risk level**
(`HIGH`/`MEDIUM`/`NONE`/`NOT_APPLICABLE`) per question. A **milestone** is
a saved, point-in-time snapshot of the whole review; later phases' passes
diff against it to show whether the platform's risk posture is actually
improving.

Less obviously: this entire flow has a full CLI/API surface, not just the
console wizard most people click through. That's what made a genuine,
57-question review tractable in one sitting — question sets, choices, and
answers are all just data to fetch and `update-answer` calls to make.

### The code

```bash
aws wellarchitected update-answer \
  --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
  --question-id "permissions" \
  --selected-choices sec_permissions_define sec_permissions_least_privileges \
                      sec_permissions_continuous_reduction sec_permissions_analyze_cross_account \
  --notes "..."

aws wellarchitected create-milestone \
  --workload-id "$WORKLOAD_ID" --milestone-name "phase-1-mvp-complete"
```

**The one real gotcha:** a handful of questions had a genuinely honest
answer of "nothing here yet" (observability, incident response — real
gaps, not oversights). Submitting those with an empty `--selected-choices`
left them registered as `UNANSWERED` rather than "answered, at risk" — the
Tool doesn't treat an empty selection as a real answer. Every question's
choice list includes an explicit `"None of these"` option (e.g.
`sec_incident_response_no`); selecting *that* is what correctly records an
honest "reviewed, nothing applies yet" instead of leaving the question
looking skipped.

The result — 26 `HIGH` / 19 `MEDIUM` / 7 `NONE` / 5 `NOT_APPLICABLE` across
57 questions — became [ADR 0004](../adr/0004-phase-1-well-architected-review.md),
written pillar-by-pillar (the shape a *review* ADR takes, as opposed to
0002/0003's decision-record shape) with every real gap mapped to the future
phase that already owns it, rather than treated as a new backlog.

---

## 6. Glossary

| Term | Definition |
|---|---|
| **Athena workgroup** | A resource-management boundary for a set of Athena queries: default output location, whether that location is enforced, cost/metrics settings. |
| **`bytes_scanned_cutoff_per_query`** | A per-query cap on how much data Athena may scan before failing the query — a hard cost guardrail. |
| **CTAS** | `CREATE TABLE AS SELECT` — creating a new table directly from a query's result, rather than declaring its schema separately. |
| **AWS CLI named profile (role chaining)** | A profile in `~/.aws/config` with `role_arn` + `source_profile`, letting any AWS SDK/CLI tool assume a role transparently with no assume-role code written. |
| **Wildcard ARN scoping** | Using `*` inside an IAM resource ARN string to match a set of resources by name pattern (e.g. every table starting `fct_`), ordinary IAM matching, not a per-service feature. |
| **dbt** | A transformation tool: write a model as a SQL `SELECT`, dbt handles materializing it as a table/view and tracking dependencies between models. |
| **dbt source** | `{{ source(...) }}` — a reference to data a dbt project reads but didn't create. |
| **dbt materialization** | How dbt persists a model's result: `view` (saved query, re-run on read) or `table` (executed once, stored as a real table). |
| **Window function** | A SQL function computed across a group of related rows (a "window") without collapsing them into one row, e.g. `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`. |
| **Fact table** | One row per business event, referencing related entities by ID rather than embedding their attributes. |
| **Dimension table** | One row per entity, holding its descriptive attributes, deduplicated. |
| **`force_destroy`** | A resource-level flag telling a provider to bypass its "must be empty first" safety check and delete contents along with the resource. |
| **Cascade delete** | A parent resource's deletion automatically deleting everything nested under it (e.g. a Glue database and all its tables), as opposed to requiring the children be removed first. |
| **AWS Well-Architected Tool** | AWS's structured self-review service: define a workload, answer best-practice questions per pillar under a lens, get a computed risk level and improvement plan. |
| **Workload (Well-Architected Tool)** | The thing being reviewed — a named, described unit the Tool tracks answers and milestones against. |
| **Lens** | A question set applied to a workload in the Well-Architected Tool — the Framework lens is the default; others (e.g. Data Analytics) add domain-specific questions. |
| **Milestone (Well-Architected Tool)** | A saved, point-in-time snapshot of a workload's review, used to diff risk posture across time. |
