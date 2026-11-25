# ADR status

The running note of ADR status (owner request, 2026-11-25). The full list of
ADRs with dates is generated in [traceability.md](traceability.md); this page
tracks what is open and why each newly Accepted ADR was accepted.

## Current

| ADRs | Status |
|---|---|
| 0001–0029 | Accepted |
| [0030](adr/0030-launch-day.md) launch day | Proposed (2026-11-25). Stays Proposed until after Thursday 2026-11-26 |

Pending on 0030: one Status line each in 0011 and 0018 (amended) and 0017
(extended) still says "Proposed". They change together with 0030.

## Rule from 2026-11-25

- The owner receives status updates. The agents carry the case for acceptance.
- Before an ADR moves to Accepted, its record below states: the design
  decisions, the pros and what was given up, what was tested (with the run,
  test or PR), and what is still unverified. A claim with no evidence is
  marked "not tested".
- The change to Accepted is its own PR with that record in it. The owner's
  "merge #N" is the final gate.
- 0001–0029 were accepted before this rule and are not back-filled. Some of
  them (0027, 0028) were accepted as designs before they were built.

## Goals

An ADR's goal is reached when the ADR is Accepted under this rule.

| ADR | Goal name (proposed) | Well-Architected milestone |
|---|---|---|
| 0030 | Cerberus Launch Day | `phase-17-launch-day-complete` |

## Acceptance record: 0030 (open)

| Claim to prove | Evidence needed | State |
|---|---|---|
| Admin permissions are sufficient and valid | policy validation and simulate check (17.3a) | partly tested: simulated before attach; not attached, no real apply |
| Generator is deterministic; IDs unique within a run | 17.2 unit tests | not tested |
| Byte guard refuses over budget; nftables quota stops traffic | 17.4 tests, Run A | not tested |
| No cookie gives 403; licence 403 then 200 | Run A | not tested |
| Signature checks run before the licence Function | Run A | not tested |
| Destroy leaves nothing; stage 2 time | Run A, `launch-check` = 0 | not tested |
| No client IP or account ID in bronze | `collect.sh` check, Run A | not tested |
| Spend stays under $25 attributable | ledger, then Cost Explorer (17.9) | not tested |
