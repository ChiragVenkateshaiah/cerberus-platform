# 5. Event-driven ingestion: EventBridge schedule vs. S3 event notification

Date: 2026-08-11

## Status

Proposed

## Context

Phase 2's goal ([plan.md](../plan.md#phase-2--event-driven-ingestion)) is to
replace the Phase 0 systemd timer with something that doesn't depend on a
logged-in session on one machine (linger is off for this user, so
`cerberus-payments.timer` already stops firing whenever the session ends —
a real, currently-live gap). The stack line names the options rather than
picking one: "Lambda triggered by S3 events / EventBridge." This ADR makes
that choice before 2.1–2.3 build against it, per this project's established
pattern of an ADR before the code it governs (0002 before 1.4, 0003 before
1.3).

The two concrete mechanisms on the table:

- **EventBridge scheduled rule** — a cron-like schedule invokes the Lambda
  directly. Pull-shaped: the same "run on a timer" model
  `cerberus-payments.timer` already uses, relocated onto managed
  infrastructure.
- **S3 event notification** — an `ObjectCreated` event on the bronze bucket
  invokes the Lambda. Push-shaped: fires the instant an object lands,
  triggered by *someone else's* write.

Working this through the Well-Architected pillars (per the method in
checkpoint.md's reference section):

| Pillar | What it asks of this decision |
|---|---|
| **Reliability** | EventBridge Scheduler supports retry policies and a flex time window natively — a genuine fix for the bug `run_payments_scheduled.sh`'s wall-clock retirement check just exposed (a systemd catch-up run firing after the retirement date silently disabled the timer instead of backfilling). An S3 event notification has no independent schedule to be reliable *about* — its reliability question is entirely "did the write that triggers it happen," which begs the question below. |
| **Security** | A scheduled rule needs only one trust relationship: EventBridge invoking the Lambda. An S3 event notification needs a second one — a Lambda resource policy letting `s3.amazonaws.com` invoke the function, scoped by a source-ARN condition to avoid a confused-deputy path. More configuration surface for a trigger this project doesn't structurally need (see tension below). |
| **Operational Excellence** | A scheduled rule maps 1:1 onto what it's replacing — a human debugging "why did ingestion run" looks for a schedule, exactly like today's timer, and can invoke the Lambda on demand the same way `generate_payments.py` is already run by hand. An S3 event trigger on a function that *is* the producer of the object that would trigger it is backwards to reason about. |
| **Cost Optimization** | Negligible either way at this volume — a few invocations a day, both mechanisms priced near zero. Not decisive. |
| **Performance Efficiency** | Push's whole advantage is reacting the instant an object lands. Irrelevant here: nothing external is landing anything, and a daily batch cadence isn't latency-sensitive. |
| **Sustainability** | Follows Cost, as in 0002/0003 — not independently decisive. |

**The tension worth naming — and the one the phase name invites getting
wrong:** "event-driven ingestion" reads as "react to an upstream event," and
an S3 event notification is the mechanism that does that literally. But
`generate_payments.py` *is* the source of the data — it doesn't consume a
file dropped by something else, it generates and writes bronze objects in
one step. An S3 event notification needs an object to already exist in S3
before it can fire; wiring one to the same function that produces that
object would mean either (a) triggering on a write the Lambda itself just
made, which is circular and buys nothing, or (b) inventing an artificial
two-step hand-off — write a "raw drop" first, then have a second Lambda
react to it — solely to make the trigger shape match the phase's name, with
no real upstream producer to justify the extra hop. That's complexity added
for its own sake, not because this pipeline's actual shape calls for it.

Read narrowly, "event-driven" in this phase is really about *what kind of
infrastructure does the scheduling* — a managed, serverless schedule instead
of a systemd timer tied to one machine's login session — not about
introducing genuine push reactivity where no upstream event exists yet. A
genuine S3-event-triggered ingestion path becomes the right decision the day
this pipeline's data source stops being self-produced — e.g. if a future
phase or a swapped-in real payments source starts *dropping* files into a
bucket for something else to pick up. That is a distinct, revisitable
decision, not this one; deferred the same way 0002 deferred a future
PII-handling ADR and 0003 picked it back up.

## Decision

**EventBridge scheduled rule, invoking the Lambda directly.** The Lambda
(2.1) wraps `generate_payments.py`'s existing core logic; the schedule rule
(2.2) replaces `cerberus-payments.timer` + `run_payments_scheduled.sh`'s
trigger role, not the generator itself — consistent with the checkpoint's
existing framing that 2.1 wraps the *same* generator rather than replacing
it. The Lambda's execution role (2.3) is scoped identically to
`cerberus-ingestion`'s existing policy (`s3:PutObject` on
`bronze/payments/*` only) — either by extending that role's trust policy to
add the Lambda's execution role as a second trusted principal, or by giving
the Lambda its own role with the same inline policy; 2.3 decides which.

S3 event notifications are explicitly **not** used for triggering ingestion
in this phase, for the reason above: there is no upstream object landing
that isn't the ingestion Lambda's own output.

## Consequences

- 2.1's Lambda is invoked on a schedule, not by a storage event — its
  handler takes no meaningful event payload from the trigger itself, only a
  scheduled-invocation signal, same as the systemd timer today.
- 2.5 retires `cerberus-payments.timer` outright once the Lambda path is
  verified end to end; nothing keeps a parallel schedule alive on this
  machine. This also permanently closes the systemd-linger blocker
  (`checkpoint.md`'s "Notes / blockers") — a managed EventBridge schedule
  doesn't depend on any login session.
- The 10-day self-retirement behavior currently living in
  `run_payments_scheduled.sh` needs a new home if it's still wanted once the
  systemd wrapper is gone (e.g. an explicit disable of the EventBridge rule,
  or dropping the auto-retirement entirely in favor of a manually-managed
  schedule) — left to 2.1/2.2 to decide, not fixed here.
- EventBridge Scheduler's native retry/DLQ support is available to 2.1 for
  handling the same class of transient-failure risk the Phase 1 review just
  fixed by hand in `generate_payments.py`'s upload loop — worth reusing
  rather than re-solving.
- If this pipeline ever gains a genuine external, uncontrolled data
  producer, the push-shaped S3 event notification path this ADR rejects
  becomes the right one for *that* producer's ingestion — a future decision,
  not a reversal of this one.
