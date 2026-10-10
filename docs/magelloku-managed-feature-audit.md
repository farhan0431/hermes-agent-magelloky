# Magelloku managed desktop feature audit

## Product boundary

The desktop is a managed Magelloku/QGIS client. Users retain chat, history, artifacts,
attachments, appearance/accessibility, and the bundled QGIS MCP execution path.

The following user-facing capability families are disabled: skills/toolset/plugin/MCP
editing, provider/model configuration and local models, arbitrary profiles/agents,
messaging integrations, webhooks, cron/kanban/bots, starmap, and generic gateway/
command-center configuration. These are blocked by policy at route classification and
native mutation IPC, rather than by CSS alone.

## Enforcement

`apps/desktop/src/lib/managed-policy.ts` is the shared policy seam. It normalizes query
and hash suffixes before matching disabled routes, so deep-link and slash/palette-style
suffixes cannot bypass the decision. Native plugin mutation handlers call the same
policy assertion before performing filesystem or git work.

This is a product boundary, not an OS security boundary. An owner with access to the
installed source, backend, Electron process, or filesystem can modify or replace the
application. Packaging/signing, filesystem ACLs, and deployment controls are required
if resistance to the machine owner is a requirement.

## Verification and remaining gaps

Focused policy tests cover disabled route families (including query/hash bypasses) and
native mutation denial. The policy still needs to be threaded through every renderer
router/palette/settings consumer and any additional Electron handlers that mutate
provider, model, profile, gateway, or plugin state. Backend authorization must also be
enforced for a threat model involving a separately reachable backend.

No claim is made that hidden routes alone remove backend capabilities; the authoritative
managed deployment should ship the backend with those APIs unavailable or authorization-
gated.

## Kept

Chat/session history, artifacts, file attachments, appearance/accessibility, and QGIS
MCP execution remain in scope.
