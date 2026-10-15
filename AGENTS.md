# AGENTS.md

Operational guidance for contributors and coding agents. Deliberately short.

**Where the rules live.** Normative statements are in `.specify/memory/constitution.md`
and `specs/001-agent-governance-platform/` (`spec.md`, `plan.md`, `data-model.md`,
`contracts/`, `adr/`). This file does not restate them. Where the two differ, the
constitution wins and this file gets fixed. Layout and commands: `README.md`, `Makefile`.

## Working in this repository

Work is spec driven: `spec.md` (what, with acceptance criteria) -> `plan.md` (how, gated
by its Constitution Check) -> `tasks.md` (order) -> implementation. Code follows the
artifacts; changing behaviour usually means changing one of them.

`$speckit-analyze`, `$speckit-converge` and the pre-implementation check are read-only:
they never touch source, templates or the constitution. `$speckit-converge` may only
append a Convergence phase to `tasks.md`.

**If you cannot verify a task, say so.** Do not mark it complete and do not present
unchecked code as finished. A recorded blocker is part of the deliverable.

## 1. Project Mission

A privately deployable governance and control platform for AI Agents, initially serving
ERP, finance and supply chain. It answers four questions for every governed action: what
exists, whether it is allowed, who authorised it, and what happened. All governed data,
processing and audit stay inside the customer's environment; it must run air-gapped.
User types and acceptance criteria: `spec.md`.

## 2. Architecture Principles

Ten principles are stated normatively in the constitution. Two properties matter more
than any other design choice:

- **Agents never reach tools directly.** The MCP gateway is the only path; an adapter
  reachable another way is a defect, not a shortcut.
- **The enforcement path fails closed.** An unevaluable dependency means refused and
  recorded, never allowed by default.

An architectural change states its trade-offs and records an ADR in `adr/`.

## 3. Code Standards

- Python 3.12; `ruff` at line length 100 with `E F W I B UP ASYNC S C4 SIM RUF`; `mypy`
  strict (`disallow_untyped_defs`, `no_implicit_optional`).
- Annotate every function under `src/`; test helpers may omit where it adds nothing.
- Fix the code, not the checker. A suppression needs the narrowest scope, a reason, and
  a tracking reference; an unused one fails the build.
- Prefer `collections.abc` types and `datetime.UTC`. Timestamps are UTC; a naive
  `datetime` is a bug. Errors carry a stable machine-readable code, not only prose.
- TypeScript strict, no unexplained `any`. Generated API types are regenerated, never
  hand-edited. Comments explain why, never what.
- Dependencies: evaluate reuse first; a new runtime dependency needs a maintained
  upstream, a licence permitting private commercial on-premises use, and a note in the
  pull request. Pin direct dependencies; a release produces an SBOM.
- Console: target WCAG 2.1 AA, and keep user-facing text at the presentation edge so
  localisation later is translation, not a rewrite.

## 4. Module Boundaries

A modular monolith, with boundaries enforced by `import-linter` (`.importlinter`) in CI.

- Dependencies point inward: `interface` -> `application` -> `domain`, with
  `infrastructure` implementing adapters.
- The domain layer is pure: no framework, driver, HTTP library or transport import.
- The application layer depends on ports (`gov.api.application.ports`), not adapters.
- Composition happens once, in the application factory; that is the only place joining
  the interface layer to an infrastructure adapter.
- Routers are transport only: parsing, authorization, error translation.
- Gateway, runner and worker are separate deployables and never import the control plane.

If you need to break a boundary, the design is wrong. Raise it; do not add an exception.

## 5. Database Specifications

- PostgreSQL 16 is the system of record. Redis is cache, locks, rate limiting and the
  local event bus, never the record of truth, and every cache key MUST include
  `organisation_id`: a key that omits it is a cross-tenant leak, invisible in review.
- All schema change goes through Alembic, with `alembic check` in CI. Manual or
  out-of-band DDL against a shared environment is prohibited. Do not edit a migration
  that is merged or applied outside your own machine.
- Forward-only with expand/contract for non-additive change; destructive changes
  document a rollback or roll-forward plan.
- Rolling upgrades must be safe: two versions may run at once, so add before you remove.
- Revision order is fixed by dependency: `0001_identity`, `0002_audit_event`,
  `0003_registry`, then the rest. Only `0002` exists and its `down_revision` names a
  migration that does not exist yet, so the chain is dangling and `alembic upgrade head`
  cannot run until `0001` lands.
- Tenancy is enforced in the data layer: `organisation_id NOT NULL` plus row-level
  security bound to `app.organisation_id`. Application filtering is not the mechanism.
- Audit is append-only, written in the same transaction as the change, and serialised
  per organisation: one writer per `organisation_id`, because `sequence` and `prev_hash`
  cannot be produced concurrently.
- Identifiers are UUIDv7. `occurred_at` is business time, `recorded_at` write time; both
  are kept. Set a per-role statement timeout and bound each connection pool so a slow
  query cannot starve enforcement.
- Retention and deletion rules are enforced and audited (FR-041); rehearse a restore
  drill and record its timing. Index foreign keys used for lookup, and constrain
  enumerations in the database, not only in Python.

## 6. API Design Specifications

- `contracts/openapi.yaml` is the contract; change it in the same change as the code.
- Validate at the boundary. Errors are RFC 9457 `application/problem+json` with a stable
  `code` and a per-field `errors` array.
- Statuses: `200` allowed or denied, `201` created, `202` held for approval, `401`,
  `403`, `404`, `409` conflict, `422`, `503` failed closed.
- Organisation comes from the token, never a parameter; identity never from a body.
- Opaque pagination tokens, page size 1..200; a malformed token is rejected.
- Latency budget: p95 policy decision under 150 ms, control-plane read under 300 ms.
  Adding a synchronous call or unbounded query there is a product change; measure it.
- Reporting reads a projection, never live operational tables.
- Concurrent updates use an optimistic check and return `409` rather than overwriting a
  colleague's change. Time comes from the server clock, never a client timestamp.
- Idempotency keys have a stated scope and lifetime: no expiry is a storage leak, no
  scope is a correctness bug. Deprecation is explicit, with a sunset and migration note.

## 7. Agent Development Specifications

- Agent identity is bound to an `agent_version`; there is no ambient authority.
- Orchestration uses LangGraph (ADR-0004). A graph orchestrates the task and never owns
  the permission decision.
- High and critical risk always require approval (FR-016), and a risk escalation while a
  request is pending is re-evaluated rather than completed.
- Every invocation carries an idempotency key; a retry returns the original outcome, not
  a second execution or approval request.
- Model and tool output is untrusted input: never evidence of identity, permission or
  intent, never rendered as markup, never allowed to widen an authorization decision.
- Delegation is explicit and both identities are audited; implicit authority between
  Agents is a confused deputy, which is a governance failure.
- Models are registered with vendor and usage restrictions; prohibited use, or use of a
  withdrawn model, is refused and recorded (FR-008).
- Evaluation uses versioned immutable datasets (FR-028); a blocking failure prevents
  release (FR-029); rollback restores the previous governed configuration, not just the
  code (FR-032).
- Unresolved business rules - risk classification, approval routing, any emergency path
  - must not be invented per feature. Raise them for a decision.

## 8. MCP Tool Development Specifications

- The gateway is the only path to a tool; a second route to an adapter is a security
  defect.
- Register a name, declared permissions (resource, action, data class), risk level,
  written risk basis and adapter reference. Incomplete registration is refused.
- Permissions are declared, never inferred from a description or model output.
- Enforcement order is fixed: identity, authorization, policy, risk, approval,
  pre-execution audit, dispatch, post-execution audit.
- Adapters execute a decision and never evaluate policy.
- Sandbox class follows risk (ADR-0006): shared restricted pool for low and medium,
  dedicated sandbox per execution for high and critical.
- The runner holds no database credentials and accepts dispatch only from the gateway's
  workload identity. Parameters are recorded as a digest, never raw sensitive values.
- Timeouts, bounded retries, payload caps and per-Agent rate limits are mandatory, and a
  timeout still produces an audit record with its reason.
- Keep `contracts/mcp-gateway.md` and the implementation in step.

## 9. Security Rules

Normative rules: constitution Principles III, IV and V, and ADRs 0003, 0005, 0007, 0008.

- Five roles, deny by default; the matrix is `gov.api.domain.identity.permissions`.
  `approval.decide` is separate from administrative status, and nobody approves their own
  request.
- OPA in `deploy/policy` is the only allow/deny authority. Python assembles the input and
  interprets the answer; it never re-implements the rule. Published policy versions are
  immutable, so roll back by republishing the previous one.
- A policy change ships with `opa test` cases for allow, deny and deny-beats-allow.
- Audit events carry a reason whenever the outcome is not success.
- Secrets live in Vault, never in source, Compose, Helm, images or fixtures.
  `deploy/compose/secrets/` is development-only and git-ignored.
- Classify data as public, internal, confidential or restricted, and redact it from logs,
  traces, metric labels and error payloads.
- Console: tokens in memory only (never `localStorage`), untrusted values rendered as
  text, restrictive CSP. The console never decides authorization.

## 10. Testing Requirements

Layers, tooling and coverage: `plan.md` ("Testing Strategy and CI Plan"). Gates:
`.github/workflows/ci.yml`. Rules that are easy to get wrong:

- Tests are mandatory for every API; a failing gate blocks merge. Every component's suite
  must actually run in CI - one that exists but never executes is not a gate.
- Prove the refused path, not only the allowed one. Fail-closed behaviour is always
  tested, including an unavailable policy engine or audit sink.
- Do not disable or weaken a test to pass. A necessary `skip` or `xfail` states its
  reason and a tracking reference, and is as narrow as possible.
- Use in-memory adapters implementing the real ports to test a use case: double the
  infrastructure, never the code under test.
- Integration tests use real PostgreSQL, not SQLite; row-level security and partial
  indexes are part of what is verified.

## 11. Git Commit Standards

- Conventional Commits, imperative, lowercase, no trailing period: `type(scope): subject`.
  Types: `feat fix docs test refactor perf build ci chore revert`. Scopes: `api gateway
  runner worker web db policy compose helm spec adr constitution`.
- Reference the task (`Refs: T042`). One logical change per commit: a migration ships with
  its model change, an ADR with the change it justifies.
- Never commit secrets, `.env`, `deploy/compose/secrets/` or `.specify/feature.json`.
- Do not rewrite published history or force-push a shared branch; your own unpublished
  branch is yours to rebase. No `--no-verify`: if a hook is wrong, fix the hook.

## 12. Prohibited Items

**Never**

- Commit secrets, tokens, private keys or real credentials, anywhere.
- Let an Agent reach a Tool outside the gateway, or add a second path to an adapter.
- Allow anything by default when a dependency is unavailable.
- Re-implement allow/deny resolution outside `deploy/policy`.
- Apply schema change outside Alembic, or edit a merged or shared-environment migration.
- Grant cross-organisation access without an explicit, policy-governed, audited exception.
- Update or delete an audit event, or write one outside its transaction.
- Deliver a stub or mock as working behaviour, or report a feature complete while its
  acceptance criteria fail.
- Take the caller's identity or organisation from a request body or parameter.
- Log, trace or return a classified value, raw parameters or a credential.
- Give the runner database credentials, ambient identity or unrestricted egress.
- Merge or deploy with a failing gate, or bypass hooks.
- Modify source, templates or the constitution from a read-only command.
- Run destructive database operations, or overwrite user data, without confirmation.

**Not without justification and a record**

- Disable, skip or weaken a test, or lower a coverage gate.
- Cross the layer boundaries in section 4.
- Make an architectural change without trade-offs and an ADR.
- Reach for bespoke code where a mature component exists.
- Add a dependency whose licence or maintenance status is unclear.

If a requirement conflicts with the constitution, an architectural flaw blocks progress,
or a security issue is found: stop and report it rather than working around it.
