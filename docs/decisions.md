# Decisions

Implementation choices where the spec left room, and where it was deliberately changed.

| # | Decision | Why |
|---|---|---|
| D1 | **Frontend auth is a backend-for-frontend (BFF)** built on `openid-client` 6 + `jose`, instead of Auth.js (`next-auth@5` is still beta) | Full control over the public/internal Keycloak URL split. Tokens stay server-side in an encrypted httpOnly cookie |
| D2 | **SSE uses native `EventSource` through a same-origin proxy** instead of a fetch-based client | With the BFF the browser authenticates by cookie, so `EventSource` works and gives `Last-Event-ID` reconnects for free. No token ever reaches the browser or a query string |
| D3 | **Static `MCP_INTERNAL_TOKEN` not used** | The per-run HMAC token proves both "internal caller" and tenant/run scope; a second shared secret adds nothing |
| D4 | **MCP server code in `mcp_servers/operations/operations_mcp/`**, with `server.py` kept as a thin entrypoint | Makes it an installable uv-workspace member that imports the backend's read services |
| D5 | **One backend Docker image** for api, worker, migrate and mcp-operations | Single lockfile and build; different commands |
| D6 | **Inner agent is not checkpointed** (`create_agent(..., checkpointer=False)`) | Otherwise it inherits the parent graph's sync checkpointer as a subgraph. A read-only investigation is safe to repeat; the parent checkpoints its result |
| D7 | **Graph runs synchronously in worker threads**; the investigate node runs the async agent with `asyncio.run` | MCP tools are async-only; the rest of the workflow uses simple sync DB transactions |
| D8 | **Offline `demo:heuristic` model is the Compose default** | `docker compose up` works without a key; the UI labels the model. A real model is one env var away |
| D9 | **Invalid proposals are stored as `failed` actions without an approval** | Operators see exactly what the model proposed and why the backend refused it |
| D10 | **One action per type per run** (duplicates in one result are dropped) | Keeps approvals unambiguous |
| D11 | **Run status precedence:** any completed action → `completed`; execution failure → `failed`/`needs_human_review`; all rejected/expired → `rejected`; otherwise `completed_no_action` | Deterministic aggregate for runs with several actions |
| D12 | **Executor refusal → `needs_review`** for `policy_changed` and `destination_changed`; **`failed`** for everything else | These two need a human decision, not a retry |
| D13 | **Per-run job serialisation** in the claim query (skip jobs whose run has another live lease) | A resume can't race a still-running start job; it waits instead |
| D14 | **Keycloak `start-dev` with realm import**, user profile with a managed `tenant_id` attribute | Keycloak 24+ drops unmanaged attributes. The profile config declares `tenant_id` as admin-only |
| D15 | **Dev-only `operations-cli` public client with password grant** | Lets `make token` and curl smoke tests get real tokens. Clearly labelled; remove for production |
| D16 | **Seed resets the demo tenants** (maintenance bypass for the triggers via `SET LOCAL app.maintenance`) | Repeatable demos and tests; the bypass is transaction-local and unused by the app |
| D17 | **Host ports configurable** (`WEB_PORT`, `API_PORT`, `KEYCLOAK_PORT`, `POSTGRES_PORT`) with the spec's defaults | Machines often already use 3000/8000/8080/5432 |
| D18 | **No ESLint in the frontend build**; `tsc --noEmit` is the frontend check | Next 16 removed `next lint`; type checking catches the important issues |
| D19 | **Tests reuse one PostgreSQL** and reseed per test with a fixed clock | Constraints, triggers, `SKIP LOCKED` and the checkpointer must be tested on real Postgres |

## Verified package versions (2026-10-30)

`mcp 2.3.0`, `langchain 1.4.7` (`langchain[mcp]` → `fastmcp 4.1.4`), `langgraph 1.2.18`,
`langgraph-checkpoint-postgres 3.2.0`, `fastapi`, `sqlalchemy 2`, Next.js 16.4.3, React 19.3.1,
openid-client 6.8.8, Keycloak 26.4.2, PostgreSQL 16. Exact versions are in `uv.lock` and
`frontend/package-lock.json`.
