# Shared contracts

The canonical interface contracts for this feature live with the specification:

- `specs/001-agent-governance-platform/contracts/openapi.yaml` (control-plane REST)
- `specs/001-agent-governance-platform/contracts/events.md` (domain events)
- `specs/001-agent-governance-platform/contracts/mcp-gateway.md` (invocation)

They are deliberately not duplicated here. Duplicating an interface contract
creates two sources of truth that drift, so this directory holds only artifacts
*generated* from the canonical documents:

- nothing yet: the generated TypeScript types are written to
  `apps/web/src/lib/api/schema.d.ts`, beside the code that imports them, by
  `npm run generate:api`.

Generation is part of the build; generated files are regenerated rather than
edited by hand.
