# ADR-0008: Keycloak for identity, Vault for secrets and keys

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture, Security
**Related**: Constitution Principle V; [research.md](../research.md) R7

## Context

Five human roles plus Agent identities must be authenticated, and the platform
holds secrets (tool credentials, database passwords) and key material (for
encrypting sensitive columns). Both must work in a private, potentially
air-gapped deployment with no mandatory egress and no reliance on a cloud
service.

## Decision

- **Human identity**: Keycloak, consumed over OIDC with authorization code and
  PKCE. The platform does not manage passwords.
- **Agent identity**: a registered identity bound to an `agent_version`, with
  key material held in Vault; Agents never receive long-lived shared secrets.
- **Secrets and keys**: HashiCorp Vault, using KV v2 for credentials and Transit
  for encryption and signing. On-premises installations may back Vault with an
  HSM via PKCS#11.
- **Service identity**: workload identity — mTLS in Kubernetes, a shared
  network identity in Compose, scoped per service.

No secret is stored in Compose files, Helm values, environment defaults, or the
repository.

## Consequences

- The platform integrates with an enterprise's existing directory rather than
  requiring a second set of credentials, which is a prerequisite for adoption.
- Both components are self-hostable and air-gap friendly, satisfying the
  deployment constraint.
- Keycloak and Vault are two additional stateful services to operate, back up
  and upgrade; this is accepted as the cost of not using cloud services.
- Cloud KMS or managed identity cannot be assumed, so application-level
  encryption through Vault Transit is the portable mechanism for protecting
  sensitive columns.

## Alternatives considered

- **Platform-managed passwords.** Rejected: weaker security posture and out of
  step with enterprise expectations; it also means operating credential
  recovery, which is pure liability.
- **Cloud identity providers (Auth0, Okta, Entra ID) and cloud KMS.**
  Rejected for the private and air-gapped deployments the requirements demand,
  where egress cannot be assumed.
- **Kubernetes Secrets as the secret store.** Rejected: it is a distribution
  mechanism, not a key management system, with no rotation, audit or
  fine-grained policy story.
- **Secrets in environment files with encryption at rest delegated to the
  host.** Rejected: no rotation story, no audit trail, and long-lived secrets
  in configuration is exactly what Principle V forbids.
