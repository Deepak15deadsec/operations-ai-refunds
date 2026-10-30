# Security

## Threat model (local demo, simulated effects)

| Threat | Mitigation | Test |
|---|---|---|
| LLM proposes a wrong or hallucinated amount | `PolicyService` recomputes eligibility and the exact amount from DB rows; mismatches are recorded as `failed/amount_mismatch` and never reach approval | E13, `test_t12_*` |
| Prompt injection in ticket or policy text | Tool outputs label customer text as untrusted; the prompt says so; and the policy check ignores model intent anyway | E08, E14, `test_t13_*` |
| Model uses another tenant's data | No tool has a tenant parameter. The tenant comes from the verified run token (MCP) or bound server-side (direct tools) | `test_tenant_comes_from_token_not_model`, eval metric "wrong-tenant data = 0" |
| Unauthenticated MCP access | MCP SDK `TokenVerifier` + `AuthSettings`; HMAC run token with audience, issuer, expiry ≤ 15 min; DNS-rebinding host allowlist; no host port | `test_t28_t35_*`, `test_raw_http_without_token_gets_401` |
| Operator approves their own run | `require_supervisor` on the endpoint plus a role check inside `approvals.decide` | `test_t14_*`, E25 |
| Cross-tenant approval or enumeration | Every query filters by the token's tenant; other tenants' objects return 404 | `test_t15_*`, `test_t27_*`, E24 |
| Malicious decision body (amount, tenant, hash) | `DecisionRequest` has `extra="forbid"`; the action is loaded by ID from the DB | `test_malicious_approval_payload_is_rejected` |
| Payload changed after approval | Immutability trigger on `proposed_actions`; SHA-256 fingerprint checked at decision **and** execution | `test_t17_*`, E34 |
| Replay or duplicate execution | Unique `dedupe_key` on jobs; unique `action_id`/`idempotency_key`/`(tenant, order)` on effects; executor returns the existing effect | `test_t04`, `test_t20`, E26, E28 |
| Stale approval (order delivered, policy changed) | Executor re-reads order and policy under row lock; fails closed (`failed` / `needs_review`) | `test_t18_*`, E29, E30 |
| Expired approval | Checked at decision and execution; the sweeper marks them `expired` | `test_t16_*`, E31 |
| Audit tampering | `BEFORE UPDATE/DELETE/TRUNCATE` trigger raises | `test_t33_*` |
| Forged or expired user token | RS256 via Keycloak JWKS; `iss`, `aud=operations-api`, `exp` required; `alg=none` rejected; tenant claim required | `test_t34_*` |
| Token theft from the browser | BFF: tokens live in an encrypted httpOnly SameSite=Lax cookie; the proxy attaches them server-side | — |
| CSRF on state-changing proxy calls | SameSite=Lax cookie plus an `Origin` check in the proxy for non-GET requests | — |
| Runaway agent | `ToolCallLimitMiddleware` (15), `ModelCallLimitMiddleware`, overall timeout, bounded structured-output retry | `test_tool_call_limit_*`, E23 |
| Secret leakage in logs, events or audit | Recursive redaction of token/secret/password/api_key keys; no tokens logged | `test_secrets_are_redacted_*` |
| Excessive input | 64 KB request body limit; bounded Pydantic fields; batch ≤ 10; per-user run rate limit | `test_t30_*` |

## Trust boundaries

1. **Browser → frontend:** cookie session only.
2. **Frontend → API:** bearer access token issued by Keycloak. The API trusts nothing else from the
   request for identity, tenant or role.
3. **Worker → MCP:** run token (HMAC, `MCP_RUN_TOKEN_SECRET`), minted per run, carrying tenant and run.
4. **LLM ↔ everything:** the model output is untrusted. It can only (a) call six read tools and
   (b) produce a schema-validated proposal, which the backend re-derives.

## Privacy

- `get_customer` returns a masked email (`a***@example.com`). The real destination address is added
  by the backend at proposal time and shown only to supervisors.
- Model context contains ticket text, order facts and policy text, nothing else.
- Optional tracing (LangSmith/Langfuse) is not enabled by default.

## Production gaps (deliberately out of scope)

- Keycloak dev mode, plain HTTP, seeded passwords and a demo session secret.
- A single shared `app` DB user for the API and worker; the MCP server uses `app_readonly`.
- An in-process rate limiter.
- The dev-only `operations-cli` client allows the password grant for scripts. Remove it in any real deployment.
