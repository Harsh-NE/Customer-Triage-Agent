# Backend (Bundle A: FastAPI + SQLite)

The HTTP API that a customer chat UI and an engineer dashboard will sit on. Code: `triage/api/`. It wraps the joint
Clarifier + Resolver graph ([INTEGRATION.md](INTEGRATION.md)), persists every conversation, and exposes customer, engineer and
analytics endpoints. No UI is included yet.

## Run it

```bash
pip install -r requirements.txt
uvicorn "triage.api.app:create_app" --factory --port 8000                  # offline: RESOLVER_LLM=fake (default)
RESOLVER_LLM=gemini uvicorn "triage.api.app:create_app" --factory --port 8000   # real model (key in .env)
# interactive docs: http://localhost:8000/docs
```

The UI is in [`frontend/`](../frontend/README.md). After `npm run build` there, this same process serves it at `/`
(`FRONTEND_DIR` overrides the folder); during development run `npm run dev` and it proxies `/api` here.

Startup loads the embedding model and both stores once (about 20 s); the first customer request is then fast.

| Env var | Default | Meaning |
|---|---|---|
| `RESOLVER_LLM` | `fake` | `fake` (offline stub) \| `gemini` \| `anthropic` \| `openai`. The Clarifier's own LLM stays off. |
| `DATABASE_URL` | `sqlite:///data/processed/docker/app.db` | case store (SQLAlchemy URL: switch to Postgres without code changes) |
| `CHECKPOINT_DB` | `data/processed/docker/checkpoints.sqlite` | LangGraph conversation state; this is what lets a conversation survive a restart |
| `APP_SECRET` | dev default | signs login tokens; use 32+ random characters |
| `ENGINEER_PASSCODE` | dev default | gate for the engineer role |
| `CORS_ORIGINS` | `http://localhost:5173` | the Vite dev server |
| `PRICING_FILE` | `triage/pricing.json` | per-model token prices |

**Auth is demo-grade**: a username signs you in (customers are created on first login); the engineer role needs the passcode.
There are no passwords. Do not expose it publicly. Swap in OIDC before real use.

## Endpoints (`/api`)

| | |
|---|---|
| `POST /auth/login` `{username, role, passcode?}` | returns `{token, user}`; send `Authorization: Bearer <token>` |
| `GET /me`, `GET /health` | identity; resolver LLM and priced models |
| **Customer** | |
| `POST /conversations` `{message}` | starts a conversation and returns it with the agent's first reply |
| `POST /conversations/{id}/messages` `{text}` or `{action: "resolved" \| "not_fixed"}` | reply; the actions are the UI's "fixed it / still failing" buttons |
| `GET /conversations`, `GET /conversations/{id}?after=<message id>` | history; the second one is the polling call (only new messages) |
| `POST /conversations/{id}/feedback` `{rating 1-5, helpful, comment}` | |
| **Engineer** | |
| `GET /cases?status=&priority=&reason=&assigned=&q=&limit=&offset=` | the queue; default `status=escalated`, ordered by priority then age |
| `GET /cases/{id}` | everything: messages, the agent's signature, ranked causes, attempts, evidence, gate result, escalation payload, activity timeline, usage and cost, notes, audit log |
| `POST /cases/{id}/reply \| assign \| priority \| notes \| resolve \| reopen` | actions; replying auto-assigns |
| **Analytics** | |
| `GET /analytics/summary \| timeseries \| cost ?days=` | dashboard tiles; `summary` returns its own `definitions` |

Message shapes the UI can rely on: a `question` message carries `payload.options` and `payload.feature` (render the options as
buttons; a typed reply also works); a `fix` message carries `payload.{diagnosis, steps, verification, sources[]}` where each
source has `official`, `url`, `license` and `trust_tier` (community answers are `official: false`). Customers never receive gate
scores or internal notes.

## Conversation status

`active` (the agent is waiting for the customer) -> `resolved` (by the agent after the customer's confirmation, or by an
engineer) | `escalated` (needs an engineer; reason code and priority P1-P4) | `declined` (out of scope or blocked; never queued
for an engineer). Any exception in the graph (LLM outage, store error) escalates the conversation as `SYSTEM_ERROR` (P2) with a
message to the customer, so nobody is left waiting on a dead thread. After an escalation the agent graph is finished and the
customer and engineer talk through plain messages.

## Data (SQLite, `triage/api/db.py`)

`users`, `conversations` (status, reason, priority, assignee, rating, resolution, plus a `summary` JSON of the agent's
findings), `messages`, `agent_events` (the Resolver's event log with tokens, cost and latency per LLM call), `case_notes`,
`case_actions` (audit trail). The conversation id is also the LangGraph thread id and the agent's ticket id.

## Tokens and cost

* Every LLM call reports real token counts from the provider (Gemini `usage_metadata` incl. thinking tokens as output, Anthropic
  and OpenAI usage); if a provider returns none, tokens are estimated as characters / 4 and flagged `estimated`.
* Prices are in `triage/pricing.json` with source and date. **Only one model is priced so far**:
  `gemini-3.5-flash-lite` at **$0.30 / 1M input and $2.50 / 1M output tokens** (cached input $0.03), from OpenRouter's public
  model list on 2026-10-08. That is OpenRouter's list price; if you call Google directly (it has a free tier) your bill can
  differ, so edit the file.
* A call on a model with no price is stored with `cost_usd = NULL` and counted as `unpriced_calls`, never as free. The
  Clarifier makes no LLM calls by default, so the cost covers the Resolver's scope check, draft and reply classification.
* Embeddings run locally (no token cost).

## Analytics definitions

`resolution_rate = resolved / (resolved + escalated)`: active conversations are unfinished and declined ones are out of scope,
so neither counts for or against the agent. `decline_rate = declined / finished`. `verify_drop_rate` = fix steps removed by the
citation check / steps drafted. Cache hit rate and average gate confidence come straight from the event log.

## Not done (deliberately or yet)

* No push channel: clients poll `GET /conversations/{id}?after=`. (A server-sent-events stream is an easy addition.)
* `promote_to_kb` is stored when an engineer resolves a case but nothing consumes it yet. B's cache cannot serve a human fix:
  its verification step needs cited evidence, which an engineer's free text does not have. The intended path is Tier 2.
* No attachments; no rate limiting; one process (a per-conversation lock prevents two simultaneous turns on one thread).
* No simulated-data seeder: a fresh dashboard is empty. Any seeded data must be labelled simulated.
* Costs for the Anthropic/OpenAI models are not in the price table.
* Tests: `tests/test_api.py` (offline, real SQLite store and checkpointer, plus one test on the real stores).
