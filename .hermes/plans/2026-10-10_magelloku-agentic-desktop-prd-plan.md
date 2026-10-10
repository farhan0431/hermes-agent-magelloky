# Magelloku Agentic Desktop Implementation Plan

> **For Hermes:** Implement task-by-task with strict TDD and preserve the fork boundary.

**Goal:** Build a zero-configuration Magelloku Agentic Desktop on the Hermes Desktop fork, focused first on QGIS, with Magelloku branding, browser login, Magelloku AI API routing, bundled Magelloku MCP/tools, and no user-side setup.

**Architecture:** React/Electron desktop remains the shell and renderer foundation. The Magelloku project is read-only reference material; its API contract, assets, MCP payload, QGIS detection, version checks, and login flow are adapted into the fork. A Magelloku runtime adapter must translate desktop chat/session behavior into the Magelloku `/api/v1/desktop/*` contract instead of pretending Magelloku is a Hermes gateway.

**Tech Stack:** Electron, React, TypeScript, Vitest, Hermes Desktop renderer/session infrastructure, Magelloku API at `https://api.magelloku.com/api/v1`, bundled QGIS MCP plugin.

---

## Product Requirements Document

### User experience

- User launches **Magelloku AI** directly; no API key, MCP URL, provider, model, or gateway configuration is required.
- First use opens the Magelloku browser authorization flow. The desktop polls the authorization request and exchanges the approved grant for a desktop bearer token.
- The default workspace is QGIS Agent. The user can type a task and receive a streamed response without configuring Hermes internals.
- QGIS MCP, skills, and tools are bundled with the application. User does not install or register MCP manually.
- The app detects QGIS and reports plugin/version readiness clearly.
- The UI uses Magelloku assets and visual tokens; Bajiki assets are not used.

### API contract

Production base URL:

```text
https://api.magelloku.com/api/v1
```

Required endpoints from `apps/api/src/routes/desktop.routes.ts` and the reference desktop client:

- `POST /desktop/auth/requests`
- `GET /desktop/auth/requests/:requestId`
- `POST /desktop/auth/requests/:requestId/poll-exchange`
- `GET /desktop/routing`
- `POST /desktop/llm/respond`
- `POST /desktop/llm/stream`
- `POST /desktop/llm/cancel` when cancellation is wired
- task/run endpoints when agent planning and accounting are integrated

### Non-goals for the first vertical slice

- Do not modify `/home/ubuntu/riset/magelloku-project`.
- Do not preserve Hermes settings/gateway surfaces that have no Magelloku purpose.
- Do not invent backend endpoints or silently fall back to a local Hermes AI provider.
- Do not claim full MCP agent execution until tool-call translation and QGIS execution are verified.
- Micromine and Surpac are reserved for later app adapters; QGIS is first.

---

## Current implementation state

Already present in the fork branch `feature/magelloku-qgis-desktop`:

- Magelloku branding assets copied from the reference project.
- Hermes blue tokens partially replaced with Magelloku green tokens.
- Bajiki logo removed from the fork.
- Bundled Magelloku QGIS MCP resources under `apps/desktop/resources/magelloku-qgis-mcp/`.
- Electron packaging includes the MCP resource directory.
- Hermes optional Bot Mode, Kanban, runtime plugin loader, and arbitrary plugin loading are disabled for this product surface.
- `apps/desktop/src/api/magelloku-client.ts` contains the initial API client and tests for auth/API bearer behavior.
- Typecheck and focused client tests pass.

Known gap: the client is not yet connected to the actual chat/session submit path. Hermes still sends `prompt.submit` to the Hermes gateway. A runtime bridge is required.

---

## Implementation tasks

### Task 1: Define the Magelloku desktop runtime boundary

**Files:**
- Modify: `apps/desktop/src/api/magelloku-client.ts`
- Create: `apps/desktop/src/api/magelloku-runtime.ts`
- Test: `apps/desktop/src/api/magelloku-runtime.test.ts`

**Behavior:** Define a small renderer-safe interface for `startBrowserAuth`, token restoration/storage, routing selection, `streamLlm`, cancellation, and session-local conversation identity. Keep all API calls under the production base URL and never expose secrets in logs.

**TDD:** Write tests proving the runtime sends `app: 'qgis'`, `modelTier`, `idempotencyKey`, messages, tools, and workspace context; run the test red; implement the smallest adapter; run green.

### Task 2: Implement browser login and secure token lifecycle

**Files:**
- Modify: `apps/desktop/src/app/gateway/hooks/use-gateway-boot.ts` or the replacement managed boot hook
- Modify: `apps/desktop/src/store/onboarding.ts`
- Modify: `apps/desktop/src/global.d.ts` only if a narrow Electron capability is required
- Test: focused login/boot tests

**Behavior:** Start an auth request, open only the returned `authorizeUrl` through the existing trusted external-link bridge, poll with bounded backoff, exchange the approved grant, persist only an encrypted/secure token, and recover from 401 by clearing the token and returning to login. Never ask the user for an API key.

### Task 3: Build a Magelloku-first startup surface

**Files:**
- Modify: `apps/desktop/src/components/boot-failure-overlay.tsx` or replace it with a managed startup surface
- Modify: `apps/desktop/src/i18n/en_boot.ts`
- Modify: `apps/desktop/src/styles.css`
- Test: startup surface tests

**Behavior:** Remove Hermes-specific recovery language and gateway settings from the normal Magelloku path. Show Magelloku logo, QGIS readiness, login state, API connectivity state, and one actionable retry path. Keep technical diagnostics available only through a deliberate diagnostics action.

### Task 4: Translate chat submit into Magelloku streaming

**Files:**
- Modify: `apps/desktop/src/app/session/hooks/use-prompt-actions/submit.ts`
- Create: `apps/desktop/src/app/session/hooks/use-prompt-actions/magelloku-submit.ts`
- Test: `magelloku-submit.test.ts`

**Behavior:** For the Magelloku managed session, convert the local transcript into Magelloku `messages`, submit to `/desktop/llm/stream`, map `message.delta` into the existing session state, finalize on `stream.completed`, and surface `stream.error`. Keep optimistic UI and cancellation semantics. Do not route Magelloku sessions through `prompt.submit`.

### Task 5: Persist local conversation identity without Hermes gateway sessions

**Files:**
- Create/modify: a focused Magelloku conversation store under `apps/desktop/src/store/`
- Modify: chat/session composition only where required
- Test: persistence and reload tests

**Behavior:** Generate a local conversation ID, persist transcript and last accepted event, restore it after restart, and keep it separate from Hermes gateway profile/session IDs. The server idempotency key must be UUID and unique per turn.

### Task 6: Wire bundled QGIS MCP and tool calls

**Files:**
- Modify: `apps/desktop/electron-builder.config.cjs`
- Modify: native QGIS bridge/electron capability surface
- Modify: Magelloku runtime tool-call handling
- Test: MCP resource/version and tool-call contract tests

**Behavior:** Discover the bundled MCP payload, verify the selected version, detect QGIS, verify plugin readiness, and execute only the approved QGIS MCP tools. Translate tool calls from Magelloku stream events into the bundled MCP process/plugin and return tool results to the model according to the API contract.

### Task 7: Remove unused Hermes product surfaces

**Files:**
- `apps/desktop/src/contrib/plugins.ts`
- navigation/routes/settings surfaces identified by focused tests
- product identity and localized copy

**Behavior:** Hide/remove settings that expose local Hermes provider, gateway, API key, Bot Mode, Kanban, messaging, cron, and arbitrary plugin configuration when not needed by Magelloku. Keep only diagnostics and managed account/QGIS controls. Removal must be additive-safe for shared code until all call sites are proven unused.

### Task 8: Verify the first vertical slice

Run from `apps/desktop`:

```bash
npx vitest run src/api/magelloku-client.test.ts src/api/magelloku-runtime.test.ts --maxWorkers=1
npm run typecheck
npm run build
```

Then verify manually/in an Electron-capable environment:

- fresh launch shows Magelloku branding, not Hermes branding;
- login opens `magelloku.com` authorization;
- approved login produces a secure token without API-key setup;
- QGIS readiness/version state is visible;
- a QGIS prompt reaches `/desktop/llm/stream` with bearer auth;
- deltas render in the chat;
- completion persists locally;
- MCP tool call executes against QGIS and returns a result;
- 401 returns to login without leaking tokens.

Commit each coherent task and push the final branch only after focused tests, typecheck, and build pass.

---

## Risks and decisions

- **API/session mismatch:** Hermes sessions are gateway-owned, while Magelloku owns desktop runs and LLM calls. The adapter must not fake Hermes RPC responses.
- **Token security:** Do not store bearer tokens in localStorage or plaintext files. Reuse the existing Electron secure-storage seam.
- **SSE correctness:** Parse `event:` plus multiple `data:` lines and require a terminal completion/error event.
- **MCP safety:** QGIS actions can mutate projects. Preserve approval/safety policy from the bundled MCP and never enable arbitrary tools by default.
- **Reference isolation:** All reads from `magelloku-project` are reference-only; no commits or writes are allowed there.
- **Visual fidelity:** Reuse the canonical Magelloku assets and palette from `apps/web/public/brand` and `apps/desktop/src/styles.css`; do not introduce Bajiki branding.

## Acceptance criteria

The task is complete only when a packaged Magelloku Agentic Desktop can be launched by a normal user, authenticated via browser, use the Magelloku API at `https://api.magelloku.com/api/v1`, stream an agent response, and invoke the bundled QGIS MCP without manual provider/MCP configuration—and the focused tests, typecheck, build, and runtime verification all pass.

---

## Recommended commits

```text
feat(desktop): add managed Magelloku runtime boundary
feat(desktop): add browser auth and secure token lifecycle
feat(desktop): replace Hermes boot recovery with Magelloku startup
feat(desktop): route managed chat through Magelloku streaming API
feat(desktop): persist Magelloku conversations locally
feat(desktop): connect bundled QGIS MCP tools
refactor(desktop): remove unused Hermes product surfaces
```
