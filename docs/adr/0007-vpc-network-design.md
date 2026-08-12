# 7. VPC network design for Spark-on-EKS

Date: 2026-08-12

## Status

Proposed

## Context

Phase 3's stack ([plan.md](../plan.md#phase-3--scalable-compute)) is Spark
on EKS, on a purpose-designed VPC — the first component in this platform
that needs real networking design at all. Everything through Phase 2 is
serverless (S3, Lambda, Glue, Athena, EventBridge); this is a genuinely new
decision space, not an extension of an existing one. It's also the first
non-free-tier phase: the EKS control plane alone runs ~$0.10/hr regardless
of load, so plan.md's cost note is explicit — provision, run the job,
`terraform destroy`; treat the whole stack (VPC included) as a
spin-up/tear-down module, not standing infrastructure. That framing shapes
this ADR as much as any pillar does: several of the "right" answers for a
production VPC are the wrong answers for a network that exists for the
lifetime of one Spark job.

The account has an existing **default VPC** (`172.31.0.0/16`, confirmed via
`aws ec2 describe-vpcs`) — not reused here, per plan.md's explicit call for
a purpose-built one; this ADR is that design, not a decision about whether
to build one.

Working the real decisions — AZ count, subnet layout, NAT strategy, EKS API
endpoint exposure, and 3.3's multi-AZ node-group shape — through the
Well-Architected pillars:

| Pillar | What it asks of the VPC/EKS network design |
|---|---|
| **Cost Optimization** | A NAT Gateway is billed hourly regardless of traffic (~$0.045/hr) plus per-GB processed. One per AZ (the standard HA pattern) doubles a fixed cost this short-lived cluster doesn't need. An S3 Gateway VPC endpoint is free and takes Spark's primary traffic — reading bronze, writing silver/gold — off the NAT Gateway's billed path entirely. |
| **Performance Efficiency** | EKS's default VPC CNI assigns each pod an IP address from the subnet's own CIDR block (not overlay networking) — an undersized subnet silently caps how many pods can schedule, a well-known small-cluster gotcha. Sizing private subnets generously avoids it even though this job needs relatively few pods. |
| **Security** | Worker nodes in private subnets (no public IP, no direct inbound path) is the EKS reference-architecture default; the NAT Gateway and S3 endpoint give them the egress they need without inbound exposure. A public EKS API endpoint is a real, accepted gap, not an oversight — this project has no VPN/bastion infrastructure and one operator, the same shape as Phase 0's `AdministratorAccess` shortcut (documented ahead of time, not discovered later). |
| **Reliability** | Two AZs (not one) is what 3.3 asks for — worker nodes spread so a single AZ's outage doesn't take the whole node group down mid-job. A single NAT Gateway is the one deliberate single point of failure this design accepts, traded for cost. |
| **Operational Excellence** | Terraform-managed subnets/route tables/NAT/IGW, tagged consistently with the rest of the project (`Project`/`Phase`). Unlike Phase 1's standing S3/IAM resources, this module gets created *and destroyed* every time the job runs (3.7) — that repetition is itself a real test of the module, not a one-time apply. |
| **Sustainability** | Follows Cost, as in every prior ADR here — a single NAT Gateway and a free S3 endpoint both minimize standing/idle infrastructure, the actual sustainability lever available at this scale. |

**The tension worth naming:** Reliability's textbook answer is one NAT
Gateway per AZ, so a NAT failure in one AZ doesn't strand that AZ's private
subnet. Cost says one NAT Gateway total. This ADR resolves it toward
**Cost**, deliberately — the failure mode a redundant NAT Gateway protects
against (an AZ-level NAT outage) only matters while infrastructure is
*running*, and this entire design exists for the duration of one Spark job,
not as always-on infrastructure that needs to survive an outage while idle.
If a NAT Gateway fails mid-job, the job is retriable — `terraform destroy`
and re-apply reconstructs the whole stack from code, unlike a stateful
service where that failure mode would mean real data loss. The same
resolution — accept a gap because the thing it protects rarely matters at
this lifecycle — is why the EKS API endpoint stays public rather than
adding a bastion/VPN this solo project has no other use for.

## Decision

**A dedicated VPC, `10.0.0.0/16`** (distinct from the account's default
`172.31.0.0/16`, avoiding any future ambiguity if the two are ever peered),
spanning **two Availability Zones** (`us-east-1a`, `us-east-1b`) — enough to
demonstrate the multi-AZ pattern 3.3 asks for, without the added resource
count (and, if NAT were per-AZ, added cost) a third AZ would bring for a
cluster that exists for one job's duration.

**Subnets, one public/private pair per AZ:**

| Subnet | CIDR | AZ | Purpose |
|---|---|---|---|
| `public-a` | `10.0.0.0/24` | `us-east-1a` | NAT Gateway, IGW route — small, no pods scheduled here |
| `public-b` | `10.0.1.0/24` | `us-east-1b` | Reserved for a future ALB/second NAT; unused by this phase's design |
| `private-a` | `10.0.16.0/20` | `us-east-1a` | EKS worker nodes |
| `private-b` | `10.0.32.0/20` | `us-east-1b` | EKS worker nodes |

Private subnets are sized `/20` (4,096 addresses each) specifically for the
VPC CNI's per-pod IP allocation headroom from the Performance Efficiency
row above — generous relative to this job's actual pod count, cheap to
provision generously since subnet sizing costs nothing by itself.

**Routing:** a single Internet Gateway attached to the VPC; public subnets
route `0.0.0.0/0` to it. A single NAT Gateway, provisioned in `public-a`
only (per the Cost/Reliability tension above); both private subnets route
`0.0.0.0/0` through it. An **S3 Gateway VPC endpoint**, attached to both
private subnets' route tables, routes S3 traffic directly rather than
through the NAT Gateway — free, and removes Spark's dominant traffic
pattern (bronze reads, silver/gold writes) from NAT's billed path.

**EKS API endpoint: public**, not private — no VPC-internal-only access
control, consistent with the Security row's accepted-gap reasoning. Worker
nodes themselves still sit in private subnets regardless; this is about API
server reachability, not node exposure.

**3.3 — multi-AZ node group:** a single managed EKS node group spanning
both `private-a` and `private-b` (not one node group per AZ) — EKS's own
Auto Scaling group spreads instances across whichever subnets the node
group is given, so one node group already delivers the multi-AZ spread
without the extra management surface of running two independently-scaled
groups for a workload with no need to scale each AZ differently. On-demand
instances, not Spot — this job runs once, briefly, and isn't the place to
add Spot interruption-handling complexity for a marginal cost saving on a
cluster that's torn down within the hour anyway. Exact instance type/count
stay Terraform variables (3.2's job to set sensible defaults), not fixed
here — the same pattern 1.4 used for `bronze_ia_transition_days`.

## Consequences

- **3.2 (EKS cluster module) and 3.3 (multi-AZ node group)** both build
  directly against this ADR's subnet layout and node-group shape — nothing
  left open for those subtasks to re-decide.
- **Accepted gaps, both deliberate and documented, not discovered later:**
  a single NAT Gateway (no cross-AZ NAT redundancy) and a public EKS API
  endpoint (no private-only access). Both trade a production-grade property
  this spin-up/destroy cluster doesn't need for lower cost and lower
  operational surface — the same category of trade as Phase 0's
  `AdministratorAccess` shortcut, and like that one, worth revisiting only
  if this module's lifecycle ever changes from "spun up per job" to
  "standing infrastructure."
- **`public-b` is provisioned but unused by this phase's actual design** —
  kept for subnet-pair symmetry and as the natural place a future ALB or
  second NAT Gateway would land, not because anything in Phase 3 needs it
  yet. If it stays unused through 3.8's Well-Architected pass, that pass
  should say so plainly rather than retrofit a justification.
- **The S3 Gateway endpoint is the one unambiguous win with no trade-off
  attached** — free, strictly reduces both cost and NAT Gateway load,
  worth confirming in 3.6's verification that Spark's S3 traffic is
  actually using it (a route-table check, not just an assumption).
- This VPC's spin-up/destroy lifecycle (3.7) means it will be created and
  destroyed repeatedly, unlike Phase 1's standing network-adjacent
  resources (there are none) — the first real test of whether this
  project's Terraform can cleanly tear down and rebuild networking
  resources, not just storage/IAM ones.
