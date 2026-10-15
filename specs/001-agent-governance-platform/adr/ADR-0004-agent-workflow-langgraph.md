# ADR-0004: LangGraph for agent workflow orchestration

**Status**: Accepted (revisit trigger defined)
**Date**: 2026-10-13
**Deciders**: Platform architecture
**Related**: [plan.md](../plan.md), [research.md](../research.md) R3

## Context

Multi-step agent workflows must be able to pause for a human approval and resume
afterwards without losing state. The platform must also ensure that a workflow
author cannot reorder or omit the governance decision, since that would
reintroduce exactly the bypass the gateway exists to prevent.

## Decision

Use LangGraph for multi-step agent workflows. The governance decision is **not**
a graph node: it is a property of the gateway that every tool call traverses.
Workflow graphs therefore orchestrate the *task*, not the *permission*.

The revisit trigger is explicit: if workflows must resume across processes at
scale, or run beyond the checkpoint model's comfortable duration envelope,
Temporal becomes the replacement.

## Consequences

- Human-in-the-loop pauses and resumption are supported without bespoke
  checkpointing code.
- Because governance sits outside the graph, an incorrectly authored workflow
  cannot grant itself access; the worst case is a workflow that fails to
  progress.
- The team depends on a young framework; the revisit trigger and the Temporal
  alternative bound the risk, and the workflow layer is deliberately the
  thinnest part of the architecture.
- Workflow state is not governance state; it is stored separately and is never
  the audit record of truth.

## Alternatives considered

- **Temporal.** Stronger durability and resumability, materially heavier to
  operate on-premises for the initial phase. Retained as the escalation path.
- **Airflow.** Batch-oriented scheduler; a poor fit for interactive,
  approval-gated, per-request workflows.
- **Bespoke state machine.** Maximum control and no dependency, but it is
  exactly the kind of novel infrastructure the reuse principle tells us to
  avoid, and it would need its own durability story.
- **No orchestration framework.** Rejected: approval-gated resumption would be
  reimplemented ad hoc, inconsistently, in every workflow.
