# Feature Specification: Permission Center

**Feature Branch**: `002-permission-center`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Implement the permission center of the Enterprise Agent Governance Platform. Objectives: provide unified authorization capabilities for the Agent Registry. User types: Platform Admin, Agent Developer, Business Owner, Auditor. Core capabilities: user management, role management, permission management, authorization for Agent resources, API permission verification, audit logging. Mandatory support: RBAC model, multi-tenant isolation, principle of least privilege, audit of permission changes, support for extending ABAC policies in the future. Acceptance criteria: administrators can create roles; administrators can bind permissions; developers can only modify Agents under their responsibility; auditors can only view logs; API requests without permissions must be rejected."

## User Scenarios & Testing *(mandatory)*

The Permission Center is the authority for **who may do what to which Agent
resource**. It lets an administrator define roles and bind permissions to them,
assign roles to people within defined scopes, and answer one question quickly and
consistently for every protected action: is this person allowed to do this, here,
now? Every change to that answer is itself recorded, so a reviewer can explain not
only what someone did but why they were able to.

### User Story 1 - Define Roles and Bind Permissions (Priority: P1)

A Platform Administrator creates a role, describes its purpose, and binds a set of
permissions to it, so that access is granted to a named responsibility rather than
to an individual. Existing roles can be reviewed and amended without changing how
the platform itself works.

**Why this priority**: nothing else in the Permission Center is possible until a
role can exist and carry permissions. This is the foundation of the RBAC model.

**Independent Test**: create a role, bind three permissions to it, read it back,
then remove one permission and confirm the role grants exactly what it now lists.

**Acceptance Scenarios**:

1. **Given** an administrator with authority to manage roles, **When** they create
   a role with a unique name and a stated purpose, **Then** the role exists in a
   state that grants nothing.
2. **Given** an existing role, **When** the administrator binds a permission to
   it, **Then** the role grants that permission and the change is recorded.
3. **Given** an existing role, **When** the administrator removes a permission,
   **Then** the role no longer grants it, and the removal is recorded with the
   permission involved.
4. **Given** a role name that already exists in the same organisation, **When** an
   administrator attempts to create it again, **Then** the creation is refused and
   the existing role is unchanged.
5. **Given** a caller without authority to manage roles, **When** they attempt to
   create a role or bind a permission, **Then** the attempt is refused and
   recorded.

---

### User Story 2 - Assign Roles Within a Scope (Priority: P1)

A Platform Administrator assigns a role to a person, optionally limited to a scope
such as a single Agent or a defined period, so that access is granted where it is
needed and no further.

**Why this priority**: a role that cannot be assigned grants nothing. This is what
turns the RBAC model into working access.

**Independent Test**: assign a role to a user for one Agent only, then confirm the
user can act on that Agent and is refused on an otherwise identical Agent.

**Acceptance Scenarios**:

1. **Given** an existing role and a known user, **When** an administrator assigns
   the role to the user, **Then** the user's effective permissions include the
   role's permissions.
2. **Given** an assignment limited to one Agent, **When** the user attempts the
   same action on a different Agent, **Then** the action is refused.
3. **Given** an assignment with an end date, **When** that date passes, **Then**
   the assignment grants nothing and the change of state is recorded.
4. **Given** an assignment, **When** an administrator revokes it, **Then** the
   user immediately loses the permissions it granted, and the revocation is
   recorded with its reason.
5. **Given** a user who already holds a role in the same scope, **When** an
   administrator assigns it again, **Then** the duplicate is refused rather than
   silently creating a second grant.

---

### User Story 3 - Every Protected Request Is Verified (Priority: P1)

A caller performs a protected action, and the platform verifies the request
against that caller's effective permissions before anything happens, so that an
unpermitted action is refused rather than attempted and then regretted.

**Why this priority**: verification is the point of the feature. A permission
model that is not enforced is documentation, not control.

**Independent Test**: with a defined role, issue a permitted request and an
otherwise identical unpermitted request, and confirm the first proceeds, the
second is refused with a reason, and both outcomes are recorded.

**Acceptance Scenarios**:

1. **Given** a caller holding a permission, **When** they make a request that
   requires it, **Then** the request proceeds.
2. **Given** a caller who does not hold the required permission, **When** they
   make the request, **Then** it is refused before any change occurs, with a
   reason that names what was missing.
3. **Given** a caller who holds no relevant permission at all, **When** they make
   the request, **Then** it is refused; nothing is permitted by default.
4. **Given** a request whose caller cannot be established, **When** it is made,
   **Then** it is refused and recorded as unauthenticated.
5. **Given** a refused request, **When** an auditor later inspects the record,
   **Then** the caller, the action, the target, the outcome and the reason are all
   present.

---

### User Story 4 - Responsibility-Based Control of Agent Resources (Priority: P2)

An Agent Developer maintains the Agents they are responsible for, and is refused
on Agents they are not, so that a growing estate does not become a free-for-all
once more than one developer is involved.

**Why this priority**: essential for safe operation at scale, but the platform can
be demonstrated with role-level control before resource-level control lands.

**Independent Test**: give a developer responsibility for one Agent, then confirm
they can modify it and cannot modify an Agent they are not responsible for.

**Acceptance Scenarios**:

1. **Given** a developer recorded as responsible for an Agent, **When** they
   modify it, **Then** the change is permitted.
2. **Given** the same developer and an Agent they are not responsible for,
   **When** they attempt the same modification, **Then** it is refused and
   recorded.
3. **Given** responsibility moving from one developer to another, **When** the
   transfer is completed, **Then** the former holder is refused and the new holder
   is permitted, and the transfer is recorded.
4. **Given** a developer whose responsibility ended, **When** they retry a
   modification, **Then** it is refused without any change to the Agent.

---

### User Story 5 - Review Who Could Do What, and Why (Priority: P2)

An Auditor reviews the history of permission changes - role creation, permission
binding, assignment, revocation - and can reconstruct why a given person held a
given permission at a given time, without being able to change anything.

**Why this priority**: an access control system that cannot explain itself is not
auditable, which is the platform's core promise.

**Independent Test**: perform a sequence of permission changes, then reconstruct
from the record alone who granted what, to whom, when, and why.

**Acceptance Scenarios**:

1. **Given** a permission change, **When** an auditor inspects the record,
   **Then** it names the actor, the target, the change, the time and the reason.
2. **Given** a point in the past, **When** the auditor asks who held a permission
   then, **Then** the answer is derived from recorded changes rather than current
   state.
3. **Given** an auditor account, **When** it attempts to create a role, bind a
   permission, or change an assignment, **Then** every such attempt is refused.
4. **Given** an attempt to alter or remove a permission-change record, **When**
   it is made, **Then** it is refused; the record is permanent.

---

### Edge Cases

Exception processes the Permission Center must define and honour:

- **No permission at all**: an identity with no assignments can do nothing beyond
  reading its own profile.
- **Conflicting grants**: where one source grants an action and another denies it
  on the same resource, the outcome is deterministic (denial wins) and both
  sources are recorded in the decision.
- **Role edited while in use**: changing a role's permissions changes the
  effective access of everyone holding it, and the change is recorded with the
  affected role so the consequence is discoverable.
- **Role in use cannot be deleted**: a role assigned to anyone is retired rather
  than removed, so past decisions remain explainable.
- **Permission removed mid-session**: a caller whose permission is revoked while
  working loses it at the next verification, not at the next sign-in.
- **Cross-organisation reference**: assigning a role to a user of another
  organisation, or scoping an assignment to another organisation's Agent, is
  refused rather than merely hidden.
- **Administrator removes their own last authority**: refused, so an organisation
  cannot be locked out of its own governance.
- **Unknown permission or unknown role**: refused; an unrecognised name grants
  nothing.
- **Clock and time zone**: assignment windows are evaluated against a single
  authoritative time, so an expiry is neither early nor late.
- **Verification unavailable**: requests requiring a permission decision are
  refused rather than allowed.

## Requirements *(mandatory)*

### Functional Requirements

**User management**

- **FR-001**: Administrators MUST be able to create, review, disable and re-enable
  users, recording a display name, an email address and an owning organisation for
  each.
- **FR-002**: Every user MUST belong to exactly one organisation, and disabling a
  user MUST immediately remove their effective permissions without erasing their
  history.

**Role management**

- **FR-003**: Administrators MUST be able to create, review, amend and retire
  roles, each with a unique name and a stated purpose.
- **FR-004**: A newly created role MUST grant no permissions until permissions are
  explicitly bound to it.
- **FR-005**: A role assigned to any user MUST NOT be deletable; it MUST be
  retired instead.

**Permission management**

- **FR-006**: Administrators MUST be able to bind permissions to a role and remove
  them, and the resulting effective permission set of the role MUST be readable.
- **FR-007**: Every permission MUST be identifiable by a stable name and a plain
  description of the action it authorises.
- **FR-008**: An unrecognised permission or role name MUST grant nothing.

**Assignment and scoping**

- **FR-009**: Administrators MUST be able to assign a role to a user, revoke an
  assignment, and record a reason for both.
- **FR-010**: An assignment MUST be scoped to an organisation, to a named Agent, or
  to both, and MUST NOT grant anything outside its scope.
- **FR-011**: An assignment MAY carry an end date, after which it MUST grant
  nothing; evaluation MUST use a single authoritative time.
- **FR-012**: A duplicate assignment of the same role to the same user in the same
  scope MUST be refused.

**Agent resource authorization**

- **FR-013**: Each Agent MUST have at least one responsible person, and the
  platform MUST record who that is.
- **FR-014**: A developer MUST be able to modify only the Agents they are
  responsible for, and MUST be refused on all others.
- **FR-015**: Responsibility for an Agent MUST be transferable, and both the
  transfer and its reason MUST be recorded.

**Verification**

- **FR-016**: Every request to a protected capability MUST be verified against the
  caller's effective permissions before any change takes effect.
- **FR-017**: Access MUST be denied by default: a request whose required
  permission is not explicitly held MUST be refused.
- **FR-018**: A refusal MUST state, in terms a business user can act on, what was
  missing; where several denials apply, all of them MUST be listed.
- **FR-019**: Verification MUST fail closed: if the decision cannot be made, the
  request MUST be refused rather than allowed.
- **FR-020**: Effective permissions MUST reflect a revocation at the next
  verification, not only at the next sign-in.

**Audit of permission change**

- **FR-021**: Every change to users, roles, permissions, assignments and Agent
  responsibility MUST be recorded with the actor, the target, the change, the
  time and the reason.
- **FR-022**: A permission-change record MUST be permanent; it MUST NOT be
  alterable or removable through the platform.
- **FR-023**: An auditor MUST be able to answer "who could do this, when, and by
  whose authority" from records alone, without consulting current state.
- **FR-024**: An auditor MUST NOT be able to create, amend or revoke any user,
  role, permission or assignment.

**Tenancy and least privilege**

- **FR-025**: All permission data that belongs to a tenant - roles, role
  permissions, assignments and accountability - MUST be scoped to an
  organisation, and no organisation's data MUST be visible to another. The
  permission catalogue is platform-wide reference data: it lists the actions the
  platform recognises and contains no organisation's information, so it is
  deliberately not tenant-scoped.
- **FR-026**: Roles and assignments MUST grant the minimum needed for the
  responsibility they describe; a role MUST NOT bundle unrelated capabilities.
- **FR-027**: An administrator MUST NOT be able to remove the last authority that
  can manage permissions in an organisation.

**Extensibility**

- **FR-028**: Authorization decisions MUST be produced by a component that can be
  extended with attribute-based rules without redesigning roles, assignments or
  existing decisions.
- **FR-029**: Where a decision is influenced by both role-based and
  attribute-based rules, the outcome MUST be deterministic, and every source that
  contributed MUST be recorded.
- **FR-030**: The platform MUST support exactly the five roles it already defines
  - Platform Administrator, Agent Developer, Security and Compliance Personnel,
  Business Approver and Auditor - and each MUST have an explicit, testable
  permission set. The four user types named in this request map onto them as
  follows: Platform Admin is the Platform Administrator role, Agent Developer is
  the Agent Developer role, Auditor is the Auditor role, and Business Owner is the
  Business Approver role, which this feature may present under its business-facing
  name. This feature adds no role and removes none.
- **FR-031**: The five built-in roles MUST remain unchanged and MUST NOT be edited
  or retired. An organisation's own roles MUST be created in addition to them, so
  that a deployment always retains a known baseline for administering the
  platform.

### Key Entities *(include if feature involves data)*

- **User**: a person recognised by the platform, with a display name, an email
  address, a status and an owning organisation.
- **Role**: a named responsibility with a stated purpose and a lifecycle of active
  or retired; grants nothing by itself.
- **Permission**: one authorised action, identified by a stable name with a plain
  description; bound to roles.
- **RoleAssignment**: the grant of a role to a user, scoped to an organisation or
  to a named Agent, optionally time-bound, with a granter and a reason.
- **ResourceScope**: the Agent, or organisation, an assignment is limited to.
- **AgentResponsibility**: the person accountable for an Agent. It is the Agent's
  owning person rather than a separate record, and its transfer history lives in
  the permission-change record rather than in a second table.
- **PermissionChangeRecord**: a permanent record of a change to any of the above,
  naming actor, target, change, time and reason.
- **AuthorizationDecision**: the outcome of verifying one request, including the
  permissions and sources consulted and the reason for the outcome.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An administrator can create a role and bind a set of permissions to
  it in under 5 minutes, and can read back the effective permission set
  immediately afterwards.
- **SC-002**: 100% of requests to protected capabilities are verified against the
  caller's permissions; zero unpermitted requests produce a change.
- **SC-003**: A developer responsible for one Agent is refused on every other
  Agent, demonstrated across at least 20 Agents and 5 developers with no
  exceptions.
- **SC-004**: An auditor can reconstruct who held a given permission at a given
  past moment, with its granting actor and reason, in under 5 minutes and without
  engineering assistance, for a sample of 20 historical changes.
- **SC-005**: 100% of permission changes are recorded, and every attempt to alter
  or remove a record fails in testing.
- **SC-006**: A revocation takes effect within one subsequent verification, with
  no successful action observed after it.
- **SC-007**: Zero cross-organisation accesses, and no visible cross-organisation
  permission data, are observed in isolation testing across all permission
  entities.
- **SC-008**: An auditor can complete every read-only review they need and perform
  no write action whatsoever; all write attempts are refused and recorded.
- **SC-009**: When a decision cannot be made, 100% of affected requests are
  refused, with none allowed by default.
- **SC-010**: Each user type this feature serves - Platform Administrator, Agent
  Developer and Auditor - can complete its primary journey on first attempt,
  measured as a task completion rate of at least 90% across a usability review
  with at least one participant per type. The Business Owner is not served by
  this feature; their journey is the approval workflow, which the platform
  specification owns.
- **SC-011**: A permission decision is produced within the platform's declared
  budget for this path - 50 ms at the 95th percentile under expected load - and
  the measured value is reported to administrators.

## Assumptions

- **Relationship to the existing platform specification**: this feature provides
  the administration and enforcement of permissions for the Agent Registry. The
  platform specification already defines five built-in roles and a fixed
  permission matrix used by its own interfaces. This feature adds runtime
  management of roles and assignments rather than replacing the built-in roles,
  which remain the deployment's guaranteed baseline.
- **Scope of the first release**: user, role, permission and assignment
  administration, responsibility-based authorization for Agent resources,
  per-request verification, and audit of permission changes. Attribute-based rules
  are anticipated but not built; the requirement is that they can be added without
  redesign.
- **Responsibility**: "under their responsibility" is assumed to mean the person
  recorded as accountable for an Agent, with a recorded transfer when that
  changes. Whether accountability may be shared is left open below.
- **Identity**: human users are assumed to authenticate through the customer's
  existing enterprise identity system; the Permission Center governs what they may
  do, not how they prove who they are.
- **Built-in roles**: the five built-in roles are immutable baselines that every
  deployment retains, so an organisation cannot remove its own ability to
  administer the platform. Organisation-specific roles are created alongside
  them, never in place of them.
- **Scale**: assumed to cover hundreds of users, dozens of roles and thousands of
  assignments per organisation, with permission checks in the request path.
- **Terminology**: "Business Owner" is the business-facing name for the existing
  Business Approver role. The two are the same role, not two grants, and the
  feature may label it either way as long as one role backs both names.
- **Audit records**: permission-change records are assumed to be retained for at
  least as long as the audit trail they accompany, with the exact period set by
  the customer's compliance policy.

**Open business rules still to be clarified**:

1. Whether one person may be accountable for an Agent, or several jointly.
2. Whether an assignment may be delegated by its holder, or only granted by an
   administrator.
3. The retention period for permission-change records.
