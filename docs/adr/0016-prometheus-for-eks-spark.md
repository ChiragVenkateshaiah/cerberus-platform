# 16. Prometheus for the EKS/Spark layer

Date: 2026-10-02

## Status

Accepted

## Context

Phase 7 was extended on 2026-10-02 ([plan.md](../plan.md#phase-7--end-to-end-platform-validation))
to add Prometheus-based metrics for the one layer Phase 6's observability
doesn't see.

**What CloudWatch already covers, and what it doesn't.** Everything
serverless or managed in this platform (the ingestion Lambda, Step
Functions, the Fargate runner tasks, Athena, the lineage collector)
publishes to CloudWatch natively. 6.1's dashboard, 6.2's alarms, and 6.5's
SLOs are all built on those metrics. **The EKS cluster and the Spark job
on it have no metrics collection at all.** Verified in code on 2026-10-02:
there are no EKS add-ons, no Container Insights, and no Prometheus. The
Spark Operator Helm release sets only `spark.jobNamespaces`, and the
SparkApplication has no metrics sink. When `RunTransform` is slow, or an
executor runs out of memory, the only evidence is the driver log. That
layer is also the platform's most expensive compute
([cost-security-summary.md](../cost-security-summary.md): `dev-compute`
exercises, meaning EKS, its nodes, and the NAT Gateway, were 56% of all
platform spend).

Prometheus is the native tool for that layer. Kubernetes components,
`kube-state-metrics`, node exporters, and Spark itself (the experimental
`PrometheusServlet` sink on the driver UI, `:4040/metrics/prometheus`)
all expose Prometheus-format endpoints.

**The workload's shape is what makes this a real decision:**

- **The cluster is ephemeral.** `dev-compute` is applied for an exercise
  and destroyed afterwards (ADR 0007, 3.7). It exists for a few hours a
  month. Anything stored inside it, such as a Prometheus TSDB or Grafana's
  database, is destroyed with it.
- **The Spark pods are short-lived.** One driver and one executor (1 vCPU,
  1 GiB each), alive for a few minutes per run. Prometheus pulls metrics,
  so a pod is only visible between scrapes, and its final moments are
  usually missed.
- **The rule every ADR since 0005 has held:** no new idle cost. The
  platform's standing infrastructure cost $0.28 across three months.

The candidates:

| Option | Where metrics live | History survives teardown | Idle cost |
|---|---|---|---|
| **A. kube-prometheus-stack, in-cluster only** | Prometheus TSDB on the cluster | No | $0 |
| **B. In-cluster Prometheus agent → Amazon Managed Service for Prometheus (AMP)**, Grafana in-cluster | AMP workspace in `dev-standing` | Yes | $0. AMP bills per sample ingested, per GB stored, and per query sample, with no workspace fee |
| **B′. Same as B, but a full Prometheus server or ADOT collector** instead of agent mode | AMP (plus a local TSDB for the server variant) | Yes | $0 |
| **B″. In-cluster Prometheus + Thanos sidecar, or a TSDB snapshot to S3 before destroy** | S3 | Yes | S3 storage only |
| **C. AMP managed collector (agentless scraper)** → AMP | AMP workspace | Yes | $0.04 per collector-hour **for as long as the scraper exists**, plus $0.03 per 10M samples collected. Zero idle only if the scraper is created and destroyed with the cluster; left standing, it is ~$29/month |
| **D. CloudWatch Container Insights**: enhanced observability ($0.21 per million observations), or **with OpenTelemetry** ($0.08/GB ingested, no per-series charge, PromQL-queryable) | CloudWatch | Yes | $0 idle |
| **E. Amazon Managed Grafana** (a viewer, combinable with B or C) | n/a | n/a (dashboards persist) | **$9/month fixed**: every workspace requires at least one editor license even if nobody logs in |

Pricing verified on 2026-10-02 against the
[AMP](https://aws.amazon.com/prometheus/pricing/),
[CloudWatch](https://aws.amazon.com/cloudwatch/pricing/), and
[Managed Grafana](https://aws.amazon.com/grafana/pricing/) pricing pages.
AMP: $0.90 per 10M samples ingested (first tier), $0.03 per GB-month
stored, $0.10 per billion query samples. The page lists a free-tier
allowance (40M samples ingested, 10 GB stored, 200B query samples) without
saying whether it's always-free or time-limited. This account is on AWS's
newer account-level free-tier plan (the Free-Tier-only EC2 restriction
noted in `terraform/modules/eks/variables.tf`), so eligibility is checked
in 7.7, not assumed.

Working the choice through the pillars (most produce little; three
produce the decision):

| Pillar | What it says |
|---|---|
| **Cost Optimization** | Rules out E outright: $9/month fixed would be the platform's first fixed monthly cost, larger than any month of real usage. Shapes C: its collector-hour charge is zero-idle only if the scraper's lifecycle is tied to the cluster's. For B, volume is tiny **if the scrape scope is bounded**. `kube-state-metrics`, node exporters, the Spark driver and the Spark Operator, with the apiserver's `/metrics` and high-cardinality cAdvisor series dropped (apiserver histograms alone can exceed 10k series), is on the order of 10k active series. At a 15s scrape: 10k × 240 scrapes/h ≈ 2.4M samples per hour of cluster lifetime (not just Spark-job minutes). That's ~$0.22/h at list price, and possibly $0 within the free-tier allowance. 7.7 measures the real series count rather than trusting this estimate. D is cheap too, since custom metrics are prorated hourly and the OTel variant has no per-series charge. Cost doesn't decide against D. |
| **Reliability** | Metrics must stay out of the pipeline's critical path, as lineage does (ADR 0013). A Prometheus or Grafana failure can't fail a Spark job. Every option satisfies this, as long as Spark's sink is passive (served on its UI port, scraped from outside) rather than pushing. **The deciding reliability question is whether history survives `terraform destroy`.** A's metrics vanish with the cluster, so comparison across future exercises (7.7's run against the next one's) is impossible. |
| **Operational Excellence** | Two observability planes, CloudWatch for serverless and Prometheus for EKS, is a real cost: two query languages, two places to look. That's the price of using each layer's native tool. It's mitigated if one Grafana can read both (a read-only CloudWatch data source next to AMP), giving a single pane where the run is visible end to end. |
| **Security** | No new ingress. Grafana is reached by `kubectl port-forward` only, with no LoadBalancer or Ingress. Unlike ADR 0013's collector, nothing is exposed. Writes to and reads from AMP are SigV4-signed via IRSA, the pattern `cerberus-spark` already uses. |
| **Performance Efficiency** | The nodes have room: 2× `m7i-flex.large` (8 GiB each) against a driver and executor with about 1.4 GiB footprint each, plus a Prometheus agent and Grafana (a few hundred MiB). A smaller scrape interval catches more of a short-lived pod's life, and in-cluster scraping allows 15s. The managed collector's floor is 30s. |
| **Sustainability** | Follows Cost: no always-on server. |

**The tension worth naming: Prometheus assumes a long-lived server, and
this platform deliberately has none.** Prometheus's normal deployment is a
standing server that scrapes continuously and keeps history locally. This
platform's entire cost story rests on compute that exists only during an
exercise. Option B resolves this by splitting the two roles. *Collection*
is ephemeral, living and dying with the cluster. *Storage* is managed and
pay-per-use, standing in `dev-standing` at zero idle cost, the same split
ADR 0013 made for lineage (ephemeral producers, S3 store). The cost of the
split is the AMP dependency and its IAM.

**The other tension: the managed collector (C) is the more "AWS-native"
answer, but it needs an architecture change.** It needs no in-cluster
agent at all. However, it requires the EKS API endpoint to include
**private** access, and ADR 0007 made it **public-only**. Enabling private
access *alongside* public is free and needs no bastion, so the operator
keeps using the public endpoint. It would arguably also remove the
NAT-before-node-group destroy gotcha (checkpoint Notes), since nodes would
reach the control plane privately instead of through the NAT. But it's an
ADR 0007 change with its own consequences to verify live, and C still has
a 30s scrape floor, a scraper lifecycle separate from the cluster's (a
scraper is deleted independently, and re-attaches to a re-created cluster
of the same name), and still needs a Grafana. (The cluster's `authentication_mode = "API"` already
meets the scraper's access-entry requirement; the endpoint is the only
blocker.) That's too much new surface to justify by itself inside 7.6. It's recorded here as the natural
follow-up if the private endpoint is ever adopted for its own reasons.

**On pull vs. short-lived pods:** a Pushgateway (push the job's final
metrics before exit) is the textbook fix. Here it would live in
`dev-compute` and die with the cluster, so it isn't standing cost. But
it's another component whose state is lost at teardown unless scraped
first, and it keeps serving a finished job's last values as if current
until they're deleted or filtered on `push_time_seconds`. For this
platform's purpose (seeing a run's resource and task behaviour while it
runs, and comparing runs afterwards), a 15s scrape of a several-minute
driver gives enough points. The lost final seconds are accepted.

**Why B over its neighbours.** B″ (Thanos sidecar or S3 snapshots) keeps
history for S3-only cost and needs no AMP IAM. But reading that history
needs a query layer (Thanos Query/Store, or restoring a snapshot into a
fresh Prometheus), which is a component to run somewhere between
exercises, exactly what this platform avoids. AMP is a managed PromQL
endpoint that a local Grafana can query at any time. Within B, agent mode
beats a full server because AMP is already the query store, so a second,
local TSDB would only duplicate it. ADOT is a legitimate equivalent
collector. Prometheus agent is chosen because it's the upstream-native
form of the same thing, with the same scrape configuration Prometheus
documentation describes.

**Why not D, including its OTel variant.** Container Insights covers the
*infrastructure* (cAdvisor, node, `kube-state-metrics` receivers). Spark's
own metrics from its servlet would still have to be pushed in separately,
for example as embedded-metric-format logs, so the Spark layer, the gap
this ADR exists for, would be the bolted-on part. With B, Spark, the
operator, and the infrastructure share one scrape path and one store, in
the format each already speaks. That is an Operational Excellence choice
(one coherent pipeline for this layer), not a cost one.

## Decision

**Option B, with a self-hosted Grafana.**

- **Storage: one AMP workspace in `envs/dev-standing`**, Terraform-managed
  and applied by CI like the other zero-idle-cost modules (lineage,
  observability). It survives every `dev-compute` teardown. Retention is
  set explicitly (`aws_prometheus_workspace_configuration`'s
  `retention_period_in_days`; AWS defaults to 150 days, maximum 1,095)
  instead of left implicit. Volume is negligible either way, but every
  other store in this repo states its lifecycle in code.
- **Collection: Prometheus in agent mode, in-cluster**, Helm-installed in
  `envs/dev-compute` next to the Spark Operator, with `kube-state-metrics`
  and the node exporter. Its scrape targets are the Spark driver, the
  Spark Operator controller's own `/metrics`, `kube-state-metrics`, and
  the node exporters. The apiserver and raw cAdvisor series are left out
  or relabel-dropped to keep cardinality bounded. It scrapes at 15s and
  `remote_write`s to AMP, using an IRSA role limited to `aps:RemoteWrite`
  on that one workspace.
  Agent mode keeps no local query store: AMP is the single source of
  truth, live and historical.
- **Spark: the native `PrometheusServlet` sink** enabled through the
  SparkApplication's `sparkConf`, and the driver pod annotated for
  discovery. No new dependency is added to the job. Executor metrics
  are expected through the driver's `/metrics/executors/prometheus`,
  behind `spark.ui.prometheus.enabled` (experimental; believed off by
  default in 3.x). Both keys are verified live on 3.5.9 in 7.7, not
  assumed here. The sink is experimental in Spark's own docs.
- **Viewing: Grafana in-cluster**, also in `dev-compute`, reached only via
  `kubectl port-forward`. It has two data sources: AMP (SigV4 via IRSA,
  query-only; recent Grafana versions handle this through the "Amazon
  Managed Service for Prometheus" data source plugin, confirmed against
  the chosen chart version in 7.7), and **CloudWatch, read-only**, so one dashboard can show a
  run end to end (Step Functions state → Spark executors → Athena). Its
  **dashboards are provisioned from JSON committed in the repo**, so they
  survive teardown in git, as the metrics do in AMP. For viewing history
  between exercises, the same JSON loads into a local Grafana
  (`docker run`) pointed at AMP with the operator's own credentials. No
  standing viewer is needed.
- **Amazon Managed Grafana and CloudWatch Container Insights are
  explicitly rejected for this project**. Managed Grafana is rejected on
  its fixed $9/month minimum per workspace. Container Insights, in either
  variant, is rejected because it covers the infrastructure natively but
  leaves Spark's own metrics as a separate, bolted-on path (see above).

## Consequences

- **A second observability plane exists**, scoped to EKS/Spark only.
  CloudWatch remains authoritative for everything 6.1–6.5 defined. The
  SLOs in [slo.md](../slo.md) don't move to Prometheus. Grafana's
  CloudWatch data source is a view onto them, not a replacement.
- **Metrics exist only for exercise windows**, which is by design. Gaps
  between exercises in AMP are the dormancy model ([slo.md](../slo.md)),
  not an outage.
- **New IAM, and two manual steps.** Two IRSA roles in `dev-compute`
  (Prometheus remote-write; Grafana AMP query + CloudWatch read), named
  `cerberus-*`, because `cerberus-admin`'s role management is scoped to
  that prefix. AMP workspace permissions for `cerberus-ci-apply`, because
  the workspace lives in the CI-applied root. But that role can't modify
  its own policy (`terraform/modules/github_oidc/main.tf`), so **the first
  `dev-standing` apply runs locally as `cerberus-admin`**. That in turn
  means `cerberus-admin` needs AMP workspace management (create, describe,
  tag, workspace configuration), plus query for the local Grafana, pushed
  as a new policy version **from the root console** first (7.3's path). In
  order: root paste, local apply, then CI handles it from there.
- **Wiring and teardown details for 7.7:** `dev-standing` outputs the
  workspace's remote-write and query endpoints, which `dev-compute` reads
  through its existing `terraform_remote_state`. Before a `dev-compute`
  teardown, give the agent time to flush its write-ahead log, and do it
  before the NAT Gateway goes: remote-write leaves the cluster through
  the NAT, so the final samples are lost otherwise.
- **The 7.4 Well-Architected review (milestone 7) predates this.** It
  touches `workload-observability` and `monitor-aws-resources` evidence,
  but Phase 7's review subtask is already closed. Whether 7.7 justifies
  re-answering those questions and saving a further milestone is a
  judgement for after 7.7 is live, recorded here so it isn't forgotten.
- **Spark's sink is experimental upstream.** If it misbehaves on 3.5.9,
  the fallback is the JMX exporter as a Java agent on the driver, which
  is more setup but stable.
- **Two things are deliberately left as follow-ups, not adopted:** the
  AMP managed collector (needs ADR 0007's private endpoint), and a
  Pushgateway for end-of-job metrics.
- **7.7 inherits the build and the live verification.** It needs a
  `dev-compute` exercise, which brackets `pipeline_active` as in 7.2. The
  same exercise can produce 7.8's demo recording, so both should be
  planned together, before the ingestion Lambda's 2026-10-15
  `RETIRE_ON_OR_AFTER`, or with that date moved.
