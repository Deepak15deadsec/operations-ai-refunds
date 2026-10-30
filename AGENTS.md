# Instructions for coding agents

The full specification is `archi.md`; implementation decisions are in `docs/decisions.md`.

## Non-negotiables
- The LLM reads and proposes only. Side effects go through `services/proposals.py` → `services/approvals.py`
  → `services/executor.py`. Never give the agent a write tool, raw SQL or a privileged token.
- Tenant, roles and amounts come from the server (verified token, DB rows), never from a request body or the model.
- Every simulated effect must be idempotent and protected by a DB unique constraint; write the domain change and
  its audit event in the same transaction.
- Money is integer minor units (`amount_minor`, INR paise). Never float.
- Add a test for every boundary you touch (policy, permissions, approvals, resumability, duplicate writes).

## Commands
- `make test` (Postgres in Docker, no LLM key), `make lint`, `make typecheck`, `make eval`
- Frontend: `cd frontend && npm run typecheck && npm run build` (Node 22)
- Full stack: `docker compose up --build`; E2E: `make seed && make e2e`

## Layout
- Domain logic: `backend/app/services/` (shared by REST, agent tools and MCP; don't duplicate rules elsewhere)
- Workflow: `backend/app/workflow/graph.py`; worker: `backend/app/worker/`
- Agent: `backend/app/agent/` (prompt, tool providers, investigator, offline models)
- MCP server: `mcp_servers/operations/operations_mcp/`
- Schema changes: add an Alembic revision in `backend/migrations/versions/`
