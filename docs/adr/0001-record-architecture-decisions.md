# 1. Record architecture decisions

Date: 2026-07-30

## Status

Accepted

## Context

`cerberus-platform` will accumulate a series of non-trivial, non-obvious
architectural choices over its phased build-out (see [plan.md](../plan.md)) —
e.g. medallion layout, Terraform state backend design, orchestration engine,
push vs. pull ingestion. Without a record, the reasoning behind these choices
is lost as soon as the moment passes, and reviewers (or future us) can only
see the *what*, not the *why*.

## Decision

We will use Architecture Decision Records (ADRs), as described by Michael
Nygard, to record every significant architectural decision made in this
project. ADRs live in `docs/adr/`, are numbered sequentially, and are never
edited after acceptance — superseding decisions get a new ADR that
references the old one.

Each ADR follows this template: Title, Date, Status
(Proposed/Accepted/Superseded), Context, Decision, Consequences.

## Consequences

- Every phase that introduces a non-obvious choice must add an ADR before
  that phase is considered done.
- The ADR log becomes part of the portfolio narrative referenced in
  [plan.md](../plan.md#portfolio-multipliers-optional-but-high-leverage).
- Superseding a decision means adding a new ADR, not editing this or any
  prior one.
