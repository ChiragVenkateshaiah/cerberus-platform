# 20. `dev-compute` nodes: an On-Demand system group, a Spot executor group, and Cluster Autoscaler

Date: 2026-10-12

## Status

Accepted (2026-10-12)

## Context

Since 3.2, `dev-compute` has one EKS managed node group: two
`m7i-flex.large` On-Demand nodes (2 vCPU, 8 GiB each), fixed at
`min = max = desired = 2`. Everything shares them: the Spark Operator, the
Prometheus agent, Grafana, kube-state-metrics, the image pre-pull
DaemonSet (#76), the Spark driver and its executors.

8.6 showed what that costs at scale. At 10M events the silver job is
**CPU-bound on two executor cores**: reading 4.4 GB of bronze JSON is 117 s
of task time on 2 slots, and partition sizing, AQE, skew and compaction
need no change (docs/scale-metrics.md, "8.6 at 10M"). Two 2 GB executors
already fill the nodes beside the system pods (#77 lowered the CPU requests
to make them fit). The 100M step (8.9) is about ten times more data, so
it needs more cores, and more cores need more nodes.

The cluster is not standing infrastructure. `make exercise` creates it,
runs one execution, and destroys it (ADR 0007, 8.3), and the exercise
ends with an account-wide check that no EKS cluster, NAT gateway, EIP or
running instance is left. A cluster lives for 35-50 minutes and runs one
job. Two more facts from earlier phases bear on this:

- **Node instances are untagged** (found 2026-10-07): a managed node group
  doesn't pass the provider's `default_tags` to the instances it launches,
  so the collector scopes cost by region, not by `Project` tag.
- **Quotas** (8.2): Spot and On-Demand vCPU quotas are 32 each.

The options, checked against the EKS user guide and pricing page on
2026-10-12:

1. **Keep two fixed On-Demand nodes.** Fails the 100M step's need for cores.
2. **Managed node groups + Cluster Autoscaler.** Managed node groups have
   a Spot capacity type with AWS's Spot practices built in: the
   `price-capacity-optimized` allocation strategy on Kubernetes 1.28+,
   several instance types per group, and **Capacity Rebalancing**. When a
   Spot node gets a rebalance recommendation, EKS launches a replacement
   and then cordons and drains the old node; if the two-minute
   interruption notice comes first, EKS drains at once, best effort. No
   separate termination handler is needed. Nodes get the
   `eks.amazonaws.com/capacityType` label, and node groups are tagged for
   Cluster Autoscaler's auto-discovery. Every instance belongs to an Auto
   Scaling group that Terraform owns. Scale-up takes about 3-4 minutes
   per node (third-party figure).
3. **Karpenter.** Launches instances directly (no Auto Scaling group),
   chooses instance types per pending pod, consolidates, and scales up in
   about a minute (third-party figure). It needs its controller on a node
   it doesn't manage (so a small managed node group anyway), a controller
   IAM role, an instance profile, and an SQS queue fed by EventBridge rules
   for Spot interruption notices -- without the queue, interruptions go
   unhandled. **The instances it launches are not in Terraform state.**
4. **EKS Auto Mode.** AWS runs the Karpenter-style provisioning, the node
   AMIs and the interruption handling. Billed as a management fee per
   second on top of EC2, independent of the purchase option (Spot does not
   discount it); the pricing page's examples are $0.02064/h for
   `m5a.xlarge` and $0.03672/h for `c6a.2xlarge`, about 12% of On-Demand.
   It also takes over the VPC CNI, storage and load-balancing add-ons and
   changes the node model.

**Forces, by pillar:**

- **Cost Optimization (the driving pillar, with Performance).** The
  executors are the elastic, interruption-tolerant part; Spot is the
  standard fit for Spark ETL (the EKS guide names it). The driver, the
  operator and the monitoring stack are not: losing the driver loses the
  run. At about one cluster-hour a day the money is small either way --
  the point is that the 100M step's extra cores come at Spot prices, and
  that nothing idles: a Spot group that starts at zero costs nothing
  until the job asks for executors.
- **Reliability, and the spin-up/destroy contract.** The single most
  important property of `dev-compute` is that `terraform destroy` leaves
  nothing running (ADR 0007; the exercise's EXIT trap and account check).
  Managed node groups keep that property: Terraform deletes the Auto
  Scaling groups, and with them every instance. Karpenter breaks it by
  design -- its nodes live outside Terraform, so a destroy that removes
  the controller before the nodes leaves instances running and billing
  until something else terminates them. That can be engineered around
  (drain and delete NodePools first, finalizers, a tag-based sweep in the
  account check), but every workaround is new failure surface on the
  teardown path, which is exactly where a mistake costs money. Spot
  interruptions themselves are a smaller risk: EKS drains Spot nodes, and
  Spark recomputes lost executor work; only the driver must not be on Spot.
- **Performance Efficiency.** Cluster Autoscaler's 3-4 minutes per
  scale-up would sit inside `RunTransform` if the job waited for it. For a
  one-job cluster, the executor capacity the job will need is known before
  the run starts, so it can be requested at apply time and be `Ready`
  before the execution -- the same move as the image pre-pull (#76).
  The autoscaler then covers what can't be known ahead: replacing an
  interrupted node, growing for dynamic allocation, and scaling to zero
  after.
- **Operational Excellence.** Option 2 adds one Helm release (Cluster
  Autoscaler) with an IRSA role. Option 3 adds a controller, CRDs
  (NodePool, EC2NodeClass), a queue, rules and roles. Option 4 adds
  nothing to run, but replaces the node model the rest of `dev-compute`
  was built and debugged on.
- **Security.** Options 2 and 3 both add one IRSA role scoped to the
  cluster's own Auto Scaling groups or instances. Option 4 moves the most
  responsibility to AWS.
- **Sustainability.** Scale-to-zero for executors and Spot's use of spare
  capacity both help; not decisive.

## Decision

**Split `dev-compute` into two managed node groups and run Cluster
Autoscaler.**

1. **`system` -- On-Demand, fixed.** One `m7i-flex.large`-class node
   (sizing confirmed in 8.8) for the Spark Operator, Prometheus, Grafana,
   kube-state-metrics, CoreDNS -- and the **Spark driver**, pinned with a node selector on
   `eks.amazonaws.com/capacityType: ON_DEMAND`.
2. **`executors` -- Spot, `min 0`.** Several instance types with the same
   vCPU and memory (the EKS guide's rule for Cluster Autoscaler with mixed
   types), tainted so only Spark executors schedule there, which tolerate
   the taint and select `capacityType: SPOT`. Its desired size is set
   **per exercise** from the planned executor count, so the nodes are
   `Ready` before the run. The image pre-pull DaemonSet (#76) tolerates
   the taint, so these nodes have the Spark image before the executors
   arrive.
3. **Cluster Autoscaler** (Helm, IRSA, auto-discovery by the node groups'
   tags), for replacement after interruptions, growth under Spark dynamic
   allocation, and scale-down to zero.
4. **A launch template per node group with `tag_specifications`**, so
   instances, volumes and network interfaces carry the `Project` tag --
   closing the untagged-instances gap from 2026-10-07 and letting the
   collector scope cost by tag.

8.8 builds and measures this: Spark dynamic allocation with shuffle
tracking, executor decommissioning on Spot drain, and a deliberate Spot
interruption (AWS FIS `aws:ec2:send-spot-instance-interruptions`) during a
run, which must end with the data-quality suite passing.

**Not chosen, and when to revisit:**

- **Karpenter** -- revisit if `dev-compute` becomes long-lived (then
  consolidation and per-pod instance choice pay off and teardown is rare),
  or if node provisioning time becomes a measured bottleneck that pre-sizing
  can't remove. Its teardown must then be designed first: NodePools
  deleted and nodes drained before the controller goes, and the account
  check extended to Karpenter-tagged instances.
- **EKS Auto Mode** -- revisit if operating the node groups and the
  autoscaler becomes the burden, accepting the ~12% fee and the node-model
  change. It would also keep the teardown property, since AWS terminates
  Auto Mode nodes with the cluster.

## Consequences

- **The 100M step gets its cores** at Spot prices, within the 32 vCPU Spot
  quota, without the system pods competing with executors.
- **Teardown stays Terraform-owned:** every node is in an Auto Scaling
  group in state, so `make exercise`'s destroy and account check work
  unchanged.
- **Accepted costs:** one more Helm release and IRSA role to maintain;
  Cluster Autoscaler's slow scale-up, mitigated by pre-sizing rather than
  removed; Spot capacity that may not be available at the moment of an
  exercise (the group's mixed types and `price-capacity-optimized` reduce
  this; a run that can't get Spot falls back to fewer executors and is
  slower, not failed -- 8.8 measures it).
- **Pod placement becomes explicit:** the driver must be pinned to
  On-Demand and executors must tolerate the Spot taint, in both
  SparkApplication manifests. A wrong selector shows up as pods stuck
  `Pending`, which the poll limit in `entrypoint_transform.sh` turns into a
  failed run, not a hang.
- **Spot interruptions become a tested path,** not an assumption: Spark
  recomputes lost executor output, and decommissioning (to be verified on
  Spark 3.5.9 in 8.8) can move shuffle blocks off a draining node first.
- **Cost reporting improves:** with tagged instances the collector can
  scope cost by `Project` instead of by region.

## Amendment (2026-10-15): what was built differs in three places

Recorded at the Phase 8 close-out review, so the ADR matches the code
(`terraform/modules/eks/main.tf`) and the measurements (docs/scale-metrics.md).

- **Executor group minimum is `--executor-nodes`, not 0.** The group runs
  with `min_size = desired_size = var.executor_desired_size` (default 1,
  set by `exercise.sh --executor-nodes`). The reason (checkpoint, 2026-10-12): with
  `min 0`, Cluster Autoscaler may remove an idle planned node before the
  Spark job starts, and the job would then pay the ~1 min scale-up again.
  This was a build-time choice, not something observed. Pinning the minimum keeps the
  planned nodes; the nodes above it still scale up and down. The cost is
  the planned nodes' idle minutes between apply and the job, a few cents
  per exercise. Scale-to-zero (Decision 2, Sustainability) is therefore
  not true inside an exercise; it is still true between exercises, when
  `dev-compute` is destroyed.
- **Cost is still scoped by region, not by `Project`.** The instances,
  volumes and ENIs are now tagged, as decided. But the collector keeps the
  region filter (`day_cost` in `collect_run_metrics.py`), so that every
  record in `observability/scale/runs/`, including the ones from before
  the tags, is priced the same way. The platform is still the only
  workload in us-east-1. The "cost reporting improves" consequence is
  available, not taken.
- **"Falls back to fewer executors" was not measured.** Spot capacity was
  available in every 8.8 and 8.9 run. The interruption test (8.8) showed
  that the run survives losing a node; a run that starts with no Spot
  capacity has not been seen. Treat it as expected, not verified.
