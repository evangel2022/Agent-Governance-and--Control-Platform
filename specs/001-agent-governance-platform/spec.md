# Feature Specification: Agent Governance and Control Platform

**Feature Branch**: `001-agent-governance-platform`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "Build an enterprise-grade Agent governance and control platform with private deployment support. The initial phase will serve ERP, finance and supply chain scenarios. Core users: Platform Administrators, Agent Developers, Security and Compliance Personnel, Business Approvers, Auditors. Initial business capabilities: (1) Agent Registry for agents, versions, owners and statuses; (2) Model Registry for models, vendors and usage restrictions; (3) Tool Registry for tools, permissions and risk levels; (4) Policy Center to configure agent tool invocation permissions and risk policies; (5) Approval Center to enforce manual approval for high-risk operations; (6) Audit Center to log agent executions, tool invocations, policy judgements and approval events; (7) Evaluation Center to manage evaluation tasks, test datasets and evaluation reports; (8) Release Center to support version release, canary rollout, rollback and decommissioning; (9) Dashboard to display operational status, risk events and governance metrics. Requirements: define permissions for each type of user; define core business processes and exception processes; define verifiable acceptance criteria for each feature; prioritize a runnable minimum viable version without building all complex features at once; do not decide the technology stack at this stage; list undetermined business rules as questions to be clarified."

## User Scenarios & Testing *(mandatory)*

The platform governs what Agents may do: which Agents exist, which Tools they may
invoke, under which policies, with which approvals, and how every governed action
is recorded. The scenarios below are ordered so that the first three independently
deliver a runnable governance loop (register, decide, approve, record) for ERP,
finance and supply chain scenarios, and later scenarios extend that loop with
model governance, investigation, release control, evaluation and reporting.

### User Story 1 - Register and Govern Agents and Tools (Priority: P1)

A Platform Administrator or Agent Developer registers an Agent, one or more of
its versions, the Tools those versions may use, each Tool's declared permissions
and risk level, and the owning person for each entry, so that the organisation has
an authoritative, current inventory of what Agents and Tools exist and who is
accountable for them.

**Why this priority**: Without an authoritative registry nothing else can be
governed; every later capability depends on this inventory.

**Independent Test**: Register an Agent, add two versions, register two Tools with
permissions and risk levels, assign owners, retire one version, and confirm the
inventory shows the correct current state while rejected duplicates and incomplete
entries are reported with actionable messages.

**Acceptance Scenarios**:

1. **Given** an authorised user and an empty registry, **When** they register an
   Agent with a name and owner, **Then** the Agent appears in the registry with a
   `draft` status and its owner attributed.
2. **Given** an existing Agent, **When** the owner adds a second version and marks
   it active, **Then** the Agent has exactly one active version and the previous
   version remains visible as superseded.
3. **Given** an existing Agent version, **When** a user registers a duplicate
   name and version, **Then** the registration is rejected with a message stating
   which identifier already exists.
4. **Given** a Tool registration missing a permission set or risk level, **When**
   the user submits it, **Then** the submission is rejected and no partial Tool is
   recorded.
5. **Given** a user whose role does not permit registry changes, **When** they
   attempt to register or retire an entry, **Then** the action is refused and the
   refusal is attributable to that user.

---

### User Story 2 - Policy-Controlled Tool Invocation with Audit Trail (Priority: P1)

A Security and Compliance user configures policies that decide whether a given
Agent may invoke a given Tool, and every invocation attempt is judged against
those policies and recorded, so that no Agent tool call can happen unobserved or
outside an explicit permission.

**Why this priority**: This is the platform's central value: turning unmanaged
Agent tool use into an explicitly permitted, recorded action.

**Independent Test**: Configure a policy permitting one Agent to use one Tool,
attempt a permitted invocation and a non-permitted invocation, and confirm the
first proceeds, the second is refused with a stated reason, and both produce
audit records naming the deciding policy.

**Acceptance Scenarios**:

1. **Given** a policy permitting Agent A to invoke Tool T, **When** Agent A
   attempts to invoke Tool T, **Then** the invocation is allowed and the
   resulting judgement names the matched policy.
2. **Given** no policy granting Agent A access to Tool T, **When** Agent A
   attempts to invoke Tool T, **Then** the invocation is denied and the denial
   reason states that no policy grants access.
3. **Given** a policy that denies Agent A access to Tool T, **When** a broader
   policy would otherwise allow it, **Then** the invocation is denied and both
   policies are recorded in the judgement.
4. **Given** any completed invocation attempt, **When** an Auditor inspects the
   audit trail, **Then** the record contains the actor, Tool, outcome, timestamp
   and the policy judgement that determined the outcome.

---

### User Story 3 - Manual Approval for High-Risk Operations (Priority: P1)

A Business Approver reviews high-risk Agent operations that policy alone cannot
authorise, and explicitly approves or rejects them with a recorded reason, so that
consequential actions in finance and supply chain require accountable human
judgement before they execute.

**Why this priority**: High-risk operations are exactly the actions the business
cannot allow to run unattended; approval completes the P1 governance loop.

**Independent Test**: Classify a Tool as high risk, attempt an invocation, confirm
it cannot proceed until a designated approver decides, then approve one request
and reject another and confirm the outcomes and reasons are recorded.

**Acceptance Scenarios**:

1. **Given** a Tool classified high risk and a permitted Agent, **When** the
   Agent attempts an invocation, **Then** the operation is held and an approval
   request is raised rather than executed.
2. **Given** a pending approval request, **When** a designated approver approves
   it with a reason, **Then** the operation proceeds and the approval is recorded
   with approver identity, time and reason.
3. **Given** a pending approval request, **When** the approver rejects it,
   **Then** the operation does not execute and the rejection reason is recorded.
4. **Given** an approval request left undecided past its configured window,
   **When** an approver opens it, **Then** the request is marked expired and
   cannot be approved.
5. **Given** a user who is not a designated approver, **When** they attempt to
   approve a high-risk request, **Then** the attempt is refused and recorded.

---

### User Story 4 - Model Registry with Vendor and Usage Restrictions (Priority: P2)

A Platform Administrator registers the models Agents rely on, records the vendor
and the permitted and prohibited uses, so that the organisation can keep
unapproved models and misuse out of finance and supply chain workflows.

**Why this priority**: Model governance is required for enterprise acceptance but
is not needed to demonstrate the P1 governance loop.

**Independent Test**: Register two models with different vendors and usage
restrictions, associate each with an Agent version, and confirm a use that the
restrictions prohibit is reported as a violation.

**Acceptance Scenarios**:

1. **Given** an authorised user, **When** they register a model with a vendor and
   at least one allowed use, **Then** the model is available for association with
   Agent versions.
2. **Given** a model whose restrictions prohibit a scenario, **When** that model
   is proposed for use in that scenario, **Then** the platform reports a usage
   restriction violation.
3. **Given** a model flagged by the vendor as withdrawn, **When** it is used, the
   attempt is refused and recorded.

---

### User Story 5 - Audit Investigation, Search and Export (Priority: P2)

An Auditor investigates what happened in a given period, searches events by actor,
Agent, Tool, outcome or approval state, and exports the result for internal or
regulatory review.

**Why this priority**: Investigation is the reason audit records exist, but it
builds on the P1 event capture.

**Independent Test**: Generate a mix of allowed, denied and approved operations,
then reconstruct one governed operation end to end from search results alone and
export the same result set.

**Acceptance Scenarios**:

1. **Given** a period containing governed operations, **When** an Auditor filters
   by outcome "denied", **Then** every denied attempt in that period is returned
   with its reason.
2. **Given** a specific invocation, **When** the Auditor follows it across policy
   judgement, approval and execution events, **Then** the full chain is visible.
3. **Given** a search result set, **When** the Auditor exports it, **Then** the
   export contains the same events and fields as the on-screen result.

---

### User Story 6 - Release Lifecycle: Release, Canary, Rollback, Decommission (Priority: P2)

An Agent Developer releases a version, gradually rolls it out, rolls it back if
it misbehaves, and finally decommissions it, with every state change recorded.

**Why this priority**: Change control matters for production use but can follow
the initial governance loop.

**Independent Test**: Release a version to a small portion of traffic, promote it
fully, roll it back to the previous version, and decommission the version,
confirming each step is recorded and the previous version is restored on
rollback.

**Acceptance Scenarios**:

1. **Given** a version that passed its required evaluations, **When** a
   developer releases it to a defined portion, **Then** only that portion is
   served by the new version and the release is recorded.
2. **Given** a partially rolled-out version, **When** the developer rolls back,
   **Then** the previous version is fully restored and the rollback is recorded
   with a reason.
3. **Given** a version with an unresolved blocking evaluation failure, **When**
   a developer attempts to release it, **Then** the release is refused.
4. **Given** a version no longer needed, **When** it is decommissioned, **Then**
   it can no longer be invoked and its decommissioning is recorded.

---

### User Story 7 - Evaluation Center (Priority: P3)

An Agent Developer or Security and Compliance user runs an evaluation of an Agent
version against a versioned test dataset and receives a report showing passing and
failing criteria.

**Why this priority**: Evaluation strengthens release confidence but is not
required for the first runnable governance loop.

**Independent Test**: Create an evaluation task against a dataset with known
outcomes, run it, and confirm the report identifies each criterion's result and an
overall outcome, and that the dataset can no longer be modified in place.

**Acceptance Scenarios**:

1. **Given** a dataset and an Agent version, **When** an evaluation task is run,
   **Then** a report is produced containing a result per criterion and an overall
   outcome.
2. **Given** a dataset already used by an evaluation, **When** a user attempts to
   change it in place, **Then** the change is refused and a new dataset version
   must be created.
3. **Given** a failing evaluation result, **When** a user views the report,
   **Then** each failing criterion names the observed versus expected outcome.

---

### User Story 8 - Governance Dashboard (Priority: P3)

A Platform Administrator or Security and Compliance user opens a dashboard that
shows current operational status, open risk events and governance metrics.

**Why this priority**: Reporting is valuable but depends on the audit and
approval data produced by earlier stories.

**Independent Test**: With a known set of operations and approvals, confirm each
dashboard figure matches a manual count of the same source data.

**Acceptance Scenarios**:

1. **Given** operations in a period, **When** the dashboard is opened, **Then**
   it shows invocation volume, denial rate, approval rate and approval latency for
   that period.
2. **Given** pending high-risk approvals, **When** the dashboard is opened,
   **Then** they are listed with age and requesting Agent.
3. **Given** a risk event, **When** the dashboard is opened, **Then** the event
   links to its underlying audit record.

---

### Edge Cases

Exception processes the platform must define and honour:

- **Policy denial**: a denied invocation must fail without side effects, return a
  stated reason, and be recorded; retrying an identical denied invocation must
  produce the same decision.
- **No matching policy**: an invocation with no matching grant must be denied
  (deny by default) rather than allowed.
- **Conflicting policies**: when one policy denies and another allows, the
  outcome must be deterministic (denial wins) and both policies must be recorded.
- **Approval rejection and expiry**: a rejected or expired request must never
  execute, including when the requester retries with identical parameters.
- **Duplicate request**: a retried high-risk request with the same idempotency
  reference must not create a second approval or a second execution.
- **Policy or approval service unavailable**: the platform must fail closed
  (deny) and record that the decision was made because the service was
  unavailable.
- **Unregistered Agent, Tool or model**: an invocation referencing an unknown or
  retired entry must be refused and recorded.
- **Risk level raised while a request is pending**: an in-flight request must be
  re-evaluated against the higher risk level rather than completing under the old
  classification.
- **Rollback failure**: if rollback cannot complete, the platform must keep the
  system in a known, recorded state and raise a risk event rather than leaving
  partial state.
- **Evaluation dataset changed after use**: prohibited; a new dataset version is
  required, and prior reports must remain reproducible.
- **Approver unavailable**: an undecided request must expire per policy; it must
  never silently execute.
- **Clock and time zone**: all recorded times must be unambiguous and comparable
  across a distributed deployment.

## Requirements *(mandatory)*

### Functional Requirements

**Users, roles and permissions**

- **FR-001**: The platform MUST support the five core user types — Platform
  Administrator, Agent Developer, Security and Compliance Personnel, Business
  Approver, and Auditor — and each MUST have an explicit, testable permission set.
- **FR-002**: The permission set MUST determine, per user type, who may register
  and retire registry entries, configure policies, approve high-risk operations,
  operate releases, manage evaluations, and view or export audit records.
- **FR-003**: Every action on a governed resource MUST be attributed to an
  authenticated identity and evaluated against that identity's permissions;
  unauthorised actions MUST be refused and recorded.
- **FR-004**: Users MUST hold only the permissions their role requires; a user
  MUST NOT be able to approve an operation they requested for that same operation
  unless an explicit, configured policy grants it.

**Agent, Tool and Model registry**

- **FR-005**: Users MUST be able to register, update and retire Agents, recording
  name, owning person, description and lifecycle status.
- **FR-006**: Agents MUST support multiple versions; each version MUST record its
  Agent, version identifier, owner, status and creation time, and each Agent MUST
  have at most one active version at a time.
- **FR-007**: Users MUST be able to register Tools with a declared permission set
  (the actions and data the Tool may access) and a risk level (low, medium, high
  or critical).
- **FR-008**: Users MUST be able to register Models with their vendor and usage
  restrictions, expressed as allowed and prohibited scenarios, data classes or
  regions.
- **FR-009**: Registration MUST reject incomplete or duplicate entries (for
  example the same name and version) with a message naming the conflicting field
  or identifier, and MUST NOT create a partial record.
- **FR-010**: Changing the risk level, permission set or usage restrictions of an
  entry that is in use MUST be recorded as a change event and MUST NOT silently
  alter the outcome of previously recorded decisions.

**Policy Center**

- **FR-011**: Authorised users MUST be able to define policies that permit or
  deny Agent-to-Tool invocation, scoped by organisation, Agent, Tool, environment
  and optionally a validity window.
- **FR-012**: Policy evaluation MUST be deterministic and deny by default: when no
  policy grants an invocation, the invocation MUST be denied.
- **FR-013**: When multiple policies match, conflict resolution MUST be
  deterministic, with denial taking precedence, and all matching policies MUST be
  listed in the recorded judgement.
- **FR-014**: Every policy judgement MUST record whether the invocation was
  allowed or denied, the matched policy or policies, the risk level applied, and
  a human-readable reason.
- **FR-015**: A change to a policy MUST take effect for subsequent invocations
  within a defined, stated period, and each judgement MUST record which policy
  version was applied.
- **FR-016**: An invocation involving a Tool classified high or critical risk MUST
  NOT proceed on policy approval alone and MUST additionally require a recorded
  approval.

**Approval Center**

- **FR-017**: The platform MUST raise an approval request for every invocation
  classified as high risk, recording the requesting identity, Agent, Tool,
  parameter digest, risk level, policy judgement and requested scope.
- **FR-018**: Designated Business Approvers MUST be able to approve or reject a
  request with a recorded reason; a rejected request MUST NOT execute.
- **FR-019**: Approval decisions MUST record approver identity and time and MUST
  be immutable once made; corrections MUST be new, additional records.
- **FR-020**: Approval requests MUST have a configurable expiry; an expired
  request MUST NOT be approvable and MUST be recorded as expired.
- **FR-021**: An approval MUST authorise only the specific request it was given
  for, unless a policy explicitly defines a scoped, time-bound standing approval.
- **FR-022**: Approvals MUST be binding at most once; a replayed or duplicated
  request with the same idempotency reference MUST NOT trigger a second execution.
  A single designated approver is sufficient by default, the number of required
  approvals MUST be configurable so dual control can be enabled without a code
  change, and a requester MUST NOT approve their own request unless an explicit,
  configured policy grants it.

**Audit Center**

- **FR-023**: The platform MUST record an audit event for every Agent execution,
  tool invocation attempt, policy judgement, approval event, registry change and
  release state change.
- **FR-024**: Each audit event MUST capture actor, action, target, timestamp,
  outcome and the governing policy or reason, and MUST be append-only and
  tamper-evident.
- **FR-025**: Authorised users MUST be able to search audit events by time range,
  actor, Agent, Tool, outcome and approval state, and MUST be able to export the
  results with the same fields shown on screen.
- **FR-026**: The audit trail MUST allow any governed invocation and its
  associated approval to be fully reconstructed from audit data alone.

**Evaluation Center**

- **FR-027**: Authorised users MUST be able to create evaluation tasks that
  reference an Agent version, a versioned test dataset and a set of evaluation
  criteria, and that produce a report with a result per criterion and an overall
  outcome.
- **FR-028**: Test datasets MUST be versioned and MUST NOT be modifiable in place
  after being used by an evaluation; changes MUST create a new version while prior
  reports remain reproducible.
- **FR-029**: A version marked as failing a blocking evaluation criterion MUST NOT
  be releasable until the failure is resolved or an authorised exception is
  recorded with a reason.

**Release Center**

- **FR-030**: Authorised users MUST be able to release a version, roll it out
  gradually to a defined portion, promote it to full, roll it back to the
  previous version, and decommission it.
- **FR-031**: Every release, promotion, rollback and decommission MUST be recorded
  as an audit event with actor, target version and reason.
- **FR-032**: Rollback MUST restore the previous version's governed configuration
  (policies, permissions and risk classification) within a defined recovery time,
  and a failed rollback MUST leave the system in a recorded, known state.

**Dashboard**

- **FR-033**: The dashboard MUST display operational status of Agents and Tools,
  open risk events, pending high-risk approvals, and governance metrics including
  invocation volume, denial rate, approval rate and approval latency.
- **FR-034**: Every dashboard figure MUST be traceable to the audit data it
  summarises, so that a figure can be reconciled with a manual count.

**Deployment, isolation and scope**

- **FR-035**: The platform MUST support private deployment, in which all governed
  data, processing and audit records remain within the customer's environment.
- **FR-036**: All governed data MUST be scoped to an organisation and records and
  searches MUST NOT expose data across organisation boundaries without an
  explicit, authorised and recorded exception. A deployment MAY host a single
  organisation or several; separation between them MUST hold in either case, so a
  single-organisation deployment is simply the one-organisation case.
- **FR-037**: The initial runnable version MUST deliver the highest-priority
  capabilities end to end rather than all capabilities partially. The first
  release is the priority-1 set: Agent and Tool registry, policy enforcement,
  audit capture and high-risk approval. Every delivered capability MUST be
  functional; empty or stub behaviour MUST NOT be presented as available.

**Exception handling**

- **FR-038**: The platform MUST define and enforce an exception process for every
  failure mode enumerated under Edge Cases. Each exception process MUST specify
  its trigger, whether the invocation is refused, and the reason that is recorded.
- **FR-039**: Every exception outcome MUST be recorded with a reason that is
  visible to authorised users and attributable to the actor or condition that
  caused it.

**Data protection, retention and service levels**

- **FR-040**: Sensitive data MUST be classified before storage and MUST be
  redacted from logs, traces, metrics and error messages, and a verification test
  MUST prove that no classified value reaches any telemetry sink.
- **FR-041**: Audit records and personal data MUST have documented retention and
  deletion rules, the platform MUST enforce the configured retention period, and
  every archival or deletion action MUST itself be recorded in the audit trail.
- **FR-042**: Every capability that exposes a service MUST declare target
  service-level objectives for availability and recovery, and the platform MUST
  report measured availability against the declared objectives. The default
  targets are 99.5% availability per calendar month for the control plane and the
  invocation path, a recovery time objective of 4 hours and a recovery point
  objective of 1 hour; a deployment MAY configure stricter targets.
- **FR-043**: Sensitive data MUST be classified using a defined taxonomy of
  `public`, `internal`, `confidential` and `restricted`, and every tool
  permission, model usage restriction and stored field that carries sensitive
  data MUST declare its class.

### Key Entities *(include if feature involves data)*

- **Organisation**: the governance boundary that owns Agents, Tools, Models,
  policies, approvals and audit records; all records belong to exactly one.
- **User**: an authenticated person with one or more roles; has identity,
  organisation and status.
- **Role**: a named permission set covering the five core user types, describing
  which actions each type may perform.
- **Agent**: a governed automated actor; has name, owner, description and
  lifecycle status.
- **AgentVersion**: a version of an Agent; belongs to one Agent, has a version
  identifier, owner, status and creation time, and at most one version per Agent
  is active.
- **Model**: a model an Agent may rely on; has vendor and usage restrictions
  (allowed and prohibited scenarios, data classes or regions).
- **Tool**: an invocable capability; has a declared permission set and a risk
  level.
- **Policy**: a rule that permits or denies Agent-to-Tool invocation within a
  scope and validity window; versioned so decisions record the version applied.
- **PolicyJudgement**: the outcome of evaluating an invocation, including the
  decision, matched policies, applied risk level and reason.
- **InvocationRecord**: a single attempt by an Agent to use a Tool, including
  parameters or their digest, linked judgement, and outcome.
- **ApprovalRequest**: a request for human authorisation of a high-risk
  invocation, with requester, scope, requested evidence and expiry.
- **ApprovalDecision**: an immutable approval or rejection with approver
  identity, timestamp and reason.
- **AuditEvent**: an append-only, tamper-evident record of a governed action,
  including actor, action, target, timestamp, outcome and reason.
- **EvaluationTask**: a run of an Agent version against a versioned dataset and
  criteria.
- **TestDataset**: a versioned collection of evaluation inputs and expected
  outcomes, immutable once used.
- **EvaluationReport**: the result of an evaluation task, with per-criterion
  results and an overall outcome.
- **Release**: a release state change (release, promote, rollback, decommission)
  for an Agent version, with actor and reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of Agent tool invocation attempts in the delivered scope
  produce a recorded policy judgement; no invocation can complete without one.
- **SC-002**: 100% of high-risk invocations fail to execute until a matching
  recorded approval exists; zero unapproved high-risk executions occur in
  verification testing.
- **SC-003**: For a sample of 20 randomly chosen governed operations, an Auditor
  can reconstruct actor, action, target, policy decision, approval and outcome
  from the audit trail alone in under 5 minutes per operation, without engineering
  assistance.
- **SC-004**: A Platform Administrator can make a newly registered Agent, its
  version and its Tools governable end to end in under 15 minutes following the
  published guidance, with no manual intervention outside the platform.
- **SC-005**: A Business Approver can decide a pending high-risk request in under
  2 minutes per request, and at least 95% of requests reach a decision within the
  configured approval window.
- **SC-006**: A policy change is reflected in judgements for new invocations
  within 5 minutes of being saved, and each judgement names the policy version
  applied.
- **SC-007**: A rollback restores the previous governed behaviour within 15
  minutes of being initiated, with no loss of audit records and no unrecorded
  intermediate state.
- **SC-008**: 100% of denied invocations and rejected or expired approvals carry a
  reason visible to authorised users; zero unexplained denials in verification
  testing.
- **SC-009**: Each of the five user types can complete its primary journey on
  first attempt, measured as a task completion rate of at least 90% across a
  usability review with at least one participant per user type.
- **SC-010**: Zero cross-organisation data exposures are observed across all
  organisation-scoped entities during isolation testing.
- **SC-011**: At least 95% of Agent tool invocations receive a recorded policy
  decision within the platform's declared latency budget under expected load
  (the budget is declared in the implementation plan and the dashboard reports
  the measured value against it).

## Assumptions

- **Minimum viable version**: the proposed first runnable version is the P1 set
  (User Stories 1-3): Agent/Tool registry, policy-controlled invocation with audit
  capture, and manual approval for high-risk operations. Model registry, audit
  investigation, release management, evaluation and dashboard are proposed for
  later increments; this boundary is confirmed as the scope of the first release.
- **Technology stack**: deliberately undecided during specification. The stack was
  decided at planning time and is recorded in plan.md and ADR-0002 (Python with
  FastAPI, React with TypeScript, PostgreSQL, Redis). This specification remains
  technology-agnostic and describes outcomes only.
- **Terminology**: "tenant" in the project constitution and "organisation" in this
  specification refer to the same governance boundary; this specification uses
  "organisation" throughout.
- **Deployment**: "private deployment" is assumed to mean the platform runs
  inside the customer's own environment, with no governed data leaving it.
- **Human identity**: human users are assumed to authenticate through the
  customer's existing enterprise identity system rather than platform-managed
  passwords; Agent identities are registered in the platform.
- **Notifications**: approvers are assumed to be notified through the customer's
  existing notification channels; the notification mechanism itself is out of
  scope for the first version.
- **Scale**: the initial phase is assumed to govern hundreds of Agents and Tools
  and thousands of invocations per day across ERP, finance and supply chain
  scenarios. The platform is designed with headroom above this assumption (see the
  performance goals in plan.md); extreme-scale behaviour is out of scope.
- **Retention**: audit records are retained for at least one year by default, with
  the exact period set by the customer's compliance policy and enforced under
  FR-041.
- **Time**: all recorded times are assumed to be unambiguous and comparable across
  environments.
- **Localisation**: a single language and a single currency presentation are
  assumed for the first version; multi-language support is out of scope.

**Open business rules still to be clarified** (to be resolved through
`$speckit-clarify` or further stakeholder input):

1. What makes a Tool "high risk" — declared per Tool by a specific role, derived
   from the data it touches, or escalated per invocation by parameters?
2. Who approves what: approval routing rules, delegation during absence, and
   escalation when an approver does not respond.
3. Whether an emergency "break-glass" path may execute a high-risk operation
   without prior approval, and if so who may invoke it and what evidence must be
   recorded.
4. Policy authoring governance: who may create or change a policy, and whether
   policy changes themselves require approval.
5. The specific classification values beyond the four-level default defined in
   FR-043 (for example, whether `internal` is further subdivided per business
   domain).
6. The specific retention and deletion periods to be configured under FR-041 for
   audit records, invocation parameters and evaluation datasets.
7. Whether full tool parameters or only a digest are stored in the audit trail,
   trading forensic usefulness against data protection.
8. Canary success and failure criteria, and whether promotion is automatic or
   manual.
9. Evaluation criteria, scoring method and pass/fail thresholds, and who owns the
   test datasets.
10. Decommissioning semantics: whether credentials, policies and data are revoked,
    archived or deleted, and after what period.
11. Data residency constraints that apply to ERP, finance and supply chain
    deployments, and how they constrain cross-border processing.
12. Whether Business Approvers are always platform users or may approve through an
    external channel.
13. Whether users may hold more than one role simultaneously, and how conflicting
    permissions are resolved (for example an approver who is also the requester).
14. Default approval time windows and the behaviour at expiry (automatic denial
    versus escalation).
