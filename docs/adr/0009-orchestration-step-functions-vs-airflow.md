# 9. Orchestration: AWS Step Functions vs. Airflow

Date: 2026-08-19

## Status

Accepted

## Context

Phase 4's goal ([plan.md](../plan.md#phase-4--orchestration)) is to turn a
sequence of jobs into a managed pipeline: "the full ingest → transform →
serve flow runs as one orchestrated state machine with retries and
visibility." plan.md's stack line already names AWS Step Functions, but
4.1 exists specifically to make that a reasoned decision against the real
alternative (Airflow) rather than an inherited assumption — the same
pattern 0005 followed for push-vs-pull ingestion.

**The orchestration this pipeline actually has today is informal, and
spread across three disconnected mechanisms:**

- **Ingestion** (2.1–2.3): EventBridge Scheduler invokes the ingestion
  Lambda daily. This already is managed, serverless scheduling — nothing
  here needs replacing.
- **Transform** (3.5/3.6): `transform/spark/submit_job.sh` is a hand-run
  bash script that uploads the Spark script, submits a `SparkApplication`
  via `kubectl apply`, then polls `kubectl get sparkapplication` in a
  `sleep 5` loop until it reports `COMPLETED`/`FAILED`, then starts an
  Athena `MSCK REPAIR TABLE` query and polls *that* execution to
  completion in a second loop. This is a real, working two-stage
  orchestration — it just lives in bash, runs by hand, and has no
  persisted execution history once the terminal closes.
- **Serving** (1.9/1.10): dbt models and the Athena demo query are also
  run by hand, with no dependency wiring to the transform step that has
  to precede them.

**The real question 4.1 has to answer isn't just "which tool" — it's
whether a fourth mechanism is justified at all**, given that 2.1–2.3
already solved scheduling and `submit_job.sh` already solved sequencing
for its own two steps. The case for adding one: none of the three existing
mechanisms can express the *full* dependency graph — ingestion must
complete before transform starts, transform before dbt, dbt before the
serving query is meaningful — as one thing. Today that graph exists only
in a human's head (run the Lambda, wait, run `submit_job.sh`, wait, run
`dbt run`, wait, run the demo query). `submit_job.sh` proves the value of
codifying a wait-and-check loop instead of eyeballing it — Step Functions
generalizes that same idea to the whole pipeline, with per-step retry
config and a persisted, visual execution history instead of scrollback in
a terminal.

Working the two options through the Well-Architected pillars (per the
method in checkpoint.md's reference section):

| Pillar | What it asks of this decision |
|---|---|
| **Cost Optimization** | The deciding pillar. Step Functions is pay-per-state-transition — a handful of transitions once a day lands well inside its perpetual free tier (4,000 transitions/month), effectively $0 at this project's volume. Airflow has no equivalent serverless mode: **MWAA** (managed) starts at ~$0.49/hr for its smallest environment — roughly $350+/month, run continuously whether or not a DAG is executing — wildly disproportionate to the existing $10/month billing alarm; **self-hosted Airflow** (EC2 or EKS) avoids the MWAA sticker price but reintroduces a standing scheduler process this project would then have to patch, size, and keep running 24/7 just to fire one daily DAG. |
| **Sustainability** | Follows Cost, as in every prior ADR here — a standing scheduler running 24/7 to occasionally fire one daily job is idle compute the pay-per-transition model doesn't carry. |
| **Operational Excellence** | Both tools win over today's status quo (Step Functions gives a persisted, visual execution graph; Airflow's UI does too) — but Step Functions wins the comparison *against Airflow* specifically because it needs no separate system to operate. There is no scheduler health to monitor, no metadata database to back up, no webserver to keep patched — the orchestration layer has the same "nothing to operate when idle" property every other Phase 1–3 compute choice in this stack already has. |
| **Reliability** | Step Functions gives per-state retry/catch as a first-class, declarative property of the state machine definition — a direct, structured upgrade over `submit_job.sh`'s two hand-rolled polling loops, which have no distinct retry policy from their surrounding bash (`set -euo pipefail` just kills the whole script). Airflow's retry model (per-task `retries`/`retry_delay`) is comparably capable — this pillar doesn't separate the two tools, it separates *either* from what exists today. |
| **Security** | Step Functions needs one IAM role for the state machine (to invoke Lambda, call the EKS/Athena APIs) — a natural extension of this project's existing per-component IAM roles (`cerberus-ingestion-lambda`, `cerberus-transform`, `cerberus-spark`). Airflow, especially self-hosted, needs its own identity and credential-storage story (Connections/Variables, or an AWS Secrets Manager backend) for reaching AWS services — a new surface this project doesn't have today and has previously decided it doesn't need (secrets management was explicitly dropped from scope during the 2026-08-03 re-scope, since no real secret exists in this stack). Not decisive alone, but it points the same direction as Cost. |
| **Performance Efficiency** | Roughly neutral for this pipeline's shape — one daily run, four sequential-ish steps, no high-frequency scheduling or massive DAG fan-out where Airflow's scheduler architecture would have a real edge. Airflow's strength here (complex branching, backfills, a large operator ecosystem) isn't a need this pipeline currently has. |

**The tension worth naming — the one 4.1's own framing in checkpoint.md
already flagged:** Airflow would be the **first non-serverless, standing
service** in this entire stack. Every other Phase 1–3 compute decision has
been either genuinely serverless (Lambda, Athena, EventBridge Scheduler)
or explicitly spin-up/destroy (EKS + Spark, per ADR 0007 and plan.md's
guiding principle 5 — "non-free resources are spun up per-exercise and
destroyed immediately"). Adding Airflow — even self-hosted rather than
MWAA — would mean introducing a service that has to exist continuously
just to fire an orchestration a few times a day, which cuts directly
against a pattern this project has held consistently for three phases. It
isn't disqualifying in principle (a portfolio project can reasonably want
to demonstrate both patterns), but there is no forcing reason here to
break it, and the cost/operational case above doesn't need that argument
to already be decisive.

**The friction point worth conceding, not glossing over:** Step Functions
has no native "run a Spark job on EKS" task type, unlike its direct SDK
integrations for Lambda, Glue, and Athena. Codifying `submit_job.sh`'s
`kubectl apply` / poll-for-`COMPLETED` logic means either (a) a Lambda
step that shells out to the Kubernetes API (`kubectl`'s underlying REST
calls, or a Python Kubernetes client, packaged the way 2.1's Lambda
already packages Faker as a layer) or (b) a container-based task (ECS
`RunTask`, itself a native Step Functions integration) running a thin
wrapper around the same logic. Either way, this is real implementation
work 4.2 has to do, not a zero-cost win — the ADR is choosing the tool,
not eliminating the transform-invocation problem `submit_job.sh` already
solved once in bash.

## Decision

**AWS Step Functions, Standard workflow type, defined as Terraform**
(`aws_sfn_state_machine`, consistent with this project's Terraform-first
convention — every other piece of infrastructure in this stack is code,
and the state machine's own IAM role and Amazon States Language
definition are no exception).

Standard, not Express: this pipeline runs once a day with a handful of
steps, not high-frequency/high-volume — Standard's exactly-once semantics
and up-to-one-year execution history (a real asset for a portfolio
project — a reviewer can look at a specific day's run months later) matter
more here than Express's higher throughput ceiling, which this workload
will never approach.

**Shape of the state machine, to be finalized in 4.2:** invoke the
existing ingestion Lambda first, then a transform step (wrapping
`submit_job.sh`'s Spark-on-EKS submission and polling logic, per the
friction point above), then a step invoking dbt's gold models, then the
Athena demo query — each step retried per its own failure mode rather than
the whole pipeline dying on the first bash-level error the way
`submit_job.sh` does today. Exactly how dbt gets invoked from inside a
state machine (a Lambda/container step, most likely) and whether the
existing EventBridge Scheduler schedule gets retargeted from the ingestion
Lambda directly to the new state machine (Step Functions is itself a valid
Scheduler target, so 2.1–2.3's scheduling infrastructure would not need to
be rebuilt, only re-pointed) are both left open, to 4.2 and 4.3
respectively — this ADR settles the tool and its execution model, not the
full graph's wiring.

Airflow (both MWAA and self-hosted) is explicitly rejected for this
project, on cost and standing-infrastructure grounds — not on capability.
Nothing about this pipeline's orchestration needs Airflow's DAG-authoring
ergonomics or operator ecosystem; what it needs is a dependency graph with
retries and visibility, which Step Functions provides at a cost and
operational footprint proportional to a solo, cost-disciplined project.

## Consequences

- The three existing informal mechanisms don't all survive unchanged.
  EventBridge Scheduler (2.1–2.3) very likely gets retargeted, not
  replaced — 4.3 decides this concretely.
  `transform/spark/submit_job.sh`'s two polling loops become a template
  for a state-machine step's logic rather than a script run by hand;
  the script itself can stay as a manual/debugging tool even after 4.2
  lands, the way `generate_payments.py` stayed runnable by hand after
  2.1 wrapped it in a Lambda (per ADR 0005).
- **4.2 inherits real, non-trivial work**, not just Terraform boilerplate:
  a Spark-on-EKS invocation path that Step Functions can call natively
  (Lambda-wrapping `kubectl`, or an ECS task) has to be built and proven
  before the state machine can include it as a step. This is conceptually
  the same class of "wraps existing logic, but not for free" cost 0005
  called out for the ingestion Lambda.
- **A new IAM role is needed** for the state machine's execution — most
  likely with narrow, per-step trust to invoke the ingestion Lambda, the
  transform step, and Athena, mirroring this project's existing
  per-component least-privilege pattern (`cerberus-ingestion-lambda`,
  `cerberus-transform`, `cerberus-spark`) rather than one broad role.
  Left to 4.2/4.3 to define exactly.
- **No new standing service is introduced.** The pipeline gains a
  dependency graph, retries, and a persisted execution history without
  breaking the serverless/spin-up-destroy pattern every prior phase has
  held — this is the ADR's central bet, and 4.5's Well-Architected pass is
  where it gets checked against what actually got built.
- **Conceded cost:** the state machine cannot orchestrate the EKS
  cluster's own lifecycle (`terraform apply`/`destroy` for the VPC/EKS
  spin-up-per-exercise pattern from ADR 0007) — that remains a human
  running Terraform, not a Step Functions responsibility. This ADR
  orchestrates *job execution* across already-provisioned infrastructure,
  not infrastructure provisioning itself; conflating the two was
  considered and rejected as scope creep for Phase 4.
- If a future phase's needs genuinely outgrow Step Functions — complex
  branching, backfills, a much larger DAG — Airflow (most likely MWAA, to
  stay managed) becomes the right re-examination, not a reversal of this
  decision's reasoning at today's scope. Nothing here forecloses that.
