<!--
DRAFT, Phase 17.8. NOT part of the /write-article Wednesday series. The owner publishes it.
Remove this whole comment before publishing.

Every {{name}} below is a placeholder. Fill it from docs/launch-day-results.md (written by
launch/results_render.py) after `make launch-results-render`. Never fill one from memory
or from a plan estimate. If the results doc reads "not measured" for a value, cut the
sentence that uses it.

  {{scale_n}}              N in 1/N. N = 33,030 Gbps divided by {{peak_gbps}}. Results doc,
                           section 6 (Scale), "Measured peak ... Gbps" [extracts/cdn_minute.csv].
  {{peak_gbps}}            Same line: measured peak, in Gbps, one region.
  {{licences_granted}}     Results doc, section 1, "Licences granted" [extracts/release_window.csv].
  {{licence_peak_minute}}  Same line, "busiest minute in one zone".
  {{early_denials}}        Same line, "licence requests refused before release".
  {{isp_top}}              Results doc, section 2, "Busiest ISP" (a synthetic label, for example isp_eu_03).
  {{isp_top_gbps}}         Same line, its peak in Gbps (modelled, not measured).
  {{isp_total_peak_gbps}}  Same line, "all ISPs together peak at" (modelled).
  {{hit_ratio_build}}      Results doc, section 3 table, hit ratio, URI class "build".
  {{hit_ratio_patch}}      Results doc, section 3 table, hit ratio, URI class "patch".
  {{patch_requests}}       extracts/cdn_class.csv, column requests, uri_class patch, the HOLD run
                           that holds Run D (not printed in the results doc: read the CSV).
  {{origin_misses_patch}}  Same CSV, column origin_misses, same row. NOTE: cdn_class is per run,
                           not per client group, so it does not split Run D cold (d-0) from warm
                           (d-1). If you want the split, read the d-0 and d-warm k6 summaries
                           in observability/launch/runs/<run_id>/results/, or drop the split.
  {{client_ttfb_p50}}, {{client_ttfb_p99}}
                           Results doc, section 4, first table, one source (k6 client, ms).
                           Client and server TTFB are different clocks: never mix them.
  {{cost_per_gb}}          Results doc, section 5, unit-cost table, "Per GB" (upper bound: all
                           attributable spend over k6 bytes). Keep the basis wording.
  {{cost_per_million}}     Same table, "Per million events".
  {{attributable_usd}}     Results doc, section 5, "Attributable spend ... of $25".

Links {{link_r1}} to {{link_r5}}: the plan (docs/plans/2026-11-25-launch-day.md, section 2)
names the outlets but holds no URL for them. Put the real article link for each.
  R1 and R2: gtaboom, DCD, player.one, americanbazaar. R3: player.one.
  R4: gtaboom, advanced-television (VMO2 survey). R5: player.one, sdxcentral.
Check each claim against its link before publishing.

Images (in docs/img/launch/, from the renderer): release-window.svg, isp-heatmap.svg,
cache-offload.svg, cost.svg, scale.svg. ttfb.svg is optional. The architecture diagram does not
exist yet: {{diagram_architecture}} (the plan section 4 sketch is the source; draw it).

BEFORE PUBLISHING
[ ] Run `make launch-results-render`; read docs/launch-day-results.md top to bottom.
[ ] Fill every placeholder above; cut any sentence whose value reads "not measured".
[ ] Check N: {{scale_n}} x {{peak_gbps}} must be about 33,030.
[ ] Check each chart opens, is the one named, and shows no account ID, ARN or domain.
[ ] Fill and check the five source links.
[ ] Make the architecture diagram and set the image.
[ ] Confirm the words "synthetic" and "one region" are still in the text.
[ ] Read once for claims: it models a launch, it does not replicate one.
[ ] Remove this comment.
-->

# Modelling a record-breaking game launch on AWS, at 1/{{scale_n}} scale

The biggest day of a game launch is not the release. It is the evening before, when millions of consoles download the same files at once and the network is the product.

In November, the German internet exchange DE-CIX recorded 33.01 Tbps across its exchanges on the day pre-loads opened ([source]({{link_r1}})). On 18 November at 20:20 CET it set a new high of 33.03 Tbps, in the last hours of downloads before the midnight-local release ([source]({{link_r2}})). DE-CIX was clear that these are total exchange peaks, not the traffic of one game ([source]({{link_r3}})). I keep that in mind below: nothing I measured can be compared to that figure as if it were the game alone.

I wanted to know whether I could model that shape end to end in one weekend, on a fixed budget, and be honest about what the model can and cannot say.

## The event

Pre-loads opened on 10 November. The download was reported at about 212 GB, and nearly half of surveyed UK players said they expected to pre-load before release day ([source]({{link_r4}})). Then there were the wobbles: one UK ISP hit a capacity problem and used emergency traffic management, and a last-minute console update on release day shook the network ([source]({{link_r5}})).

## Two planes

I built the model as two planes ({{diagram_architecture}}).

The delivery plane is a CloudFront edge in front of a private S3 bucket. A synthetic 4 GiB build is split into 64 chunks of 64 MiB, named by their content hash. A 512 MiB day-one patch sits beside it. Signed cookies gate the files. A CloudFront Function on `/license` answers 403 until a release time, then 200. Load comes from k6 on a single Spot instance, and the whole stack is destroyed after each session.

The telemetry plane is a second event family in the data platform. Synthetic consoles emit download events with the shape of the real event. They land in bronze, are promoted to silver, modelled in gold with dbt on Athena, and checked by a data-quality suite.

Two caveats up front. All telemetry is synthetic, shaped from public reports, with invented ISP and region labels. And the peak I measured is one region, one metro, 50 virtual clients: {{peak_gbps}} Gbps, which is 1/{{scale_n}} of the 33.03 Tbps exchange peak. This is the shape of a launch, not its size.

## Finding 1: a release is a set of waves, not a spike

Each time zone opens at its own midnight, so demand rolls around the world. In the release-window chart ([release-window.svg](../../docs/img/launch/release-window.svg)), the licence endpoint refused {{early_denials}} requests before release and granted {{licences_granted}} afterwards. The busiest minute in a single zone saw {{licence_peak_minute}} grants. The licence check is the real hot spot: it has no origin and no cache, so every player hits the Function at the same moment.

## Finding 2: one ISP is where it hurts

I modelled traffic per ISP from the synthetic telemetry ([isp-heatmap.svg](../../docs/img/launch/isp-heatmap.svg)). The busiest ISP, `{{isp_top}}`, peaked at {{isp_top_gbps}} Gbps, while all ISPs together peaked at {{isp_total_peak_gbps}} Gbps. This is modelled, not measured, and it shows the same pattern as the real incident: the network breaks at one ISP, long before the global total looks worrying.

## Finding 3: immutable chunks and the edge cache keep the origin quiet

Every chunk is named by its hash, so it never changes. The cache can keep it for a year and never needs to ask whether it is stale. Run D tests this: a cold patch for 50 clients at the release time, then a warm repeat by one client. The edge answered {{hit_ratio_build}} of build requests and {{hit_ratio_patch}} of patch requests from cache ([cache-offload.svg](../../docs/img/launch/cache-offload.svg)). Of {{patch_requests}} patch requests, {{origin_misses_patch}} reached the origin. When many clients ask for the same new object at once, CloudFront collapses them into one trip to the origin.

I first planned to add Origin Shield as a second cache layer, then dropped it. AWS's load-testing guidance does not allow load tests on origins with Origin Shield enabled. Also, with one client in us-east-1, the shield layer would have shown little. Immutable names plus the edge cache were enough to show the effect.

## What it cost

The attributable spend for the whole launch was {{attributable_usd}}, against a $25 stop rule I set in advance ([cost.svg](../../docs/img/launch/cost.svg)). That works out at {{cost_per_gb}} per GB delivered, an upper bound because it counts all attributable spend, and {{cost_per_million}} per million telemetry events.

## What real scale needs

My model leaves out three things a real launch cannot.

- Multi-CDN. At 33 Tbps no single CDN carries the load. Traffic is split across providers, with steering between them.
- ISP embedded caches. The biggest saving is a cache inside the ISP, so the bytes never cross the ISP's transit links at all.
- Peering at exchanges. Direct links at places like DE-CIX take the traffic off the public path.

## What I would do differently

I would test more than one metro, because the hit ratio I measured says little about a global cache. I would split cold and warm into separate log runs from the start, so the origin numbers are easy to read. And I would write the results renderer before the first live run, not after, so every chart is ready when the data lands.

The code, the plan and the decision record are open: [github.com/ChiragVenkateshaiah/cerberus-platform](https://github.com/ChiragVenkateshaiah/cerberus-platform).

One more time, to be clear: the telemetry is synthetic, the test is one region, and the exchange figures are totals, not one game. It models a launch. It does not replicate one.
