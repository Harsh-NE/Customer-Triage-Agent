# Frontend (React + Vite + TypeScript)

One app, two roles. Customers chat with the agent and see how it ended; engineers get a console over the escalated cases and the
agent's own numbers. It talks only to the backend in `triage/api` ([docs/BACKEND.md](../docs/BACKEND.md)).

Stack: React 19, React Router 7, TanStack Query (polling + cache), Tailwind CSS 4, Recharts, Vitest + Testing Library.

## Run it

```bash
# terminal 1: the API (offline stub LLM; add RESOLVER_LLM=gemini for the real model)
uvicorn "triage.api.app:create_app" --factory --port 8000

# terminal 2: the UI with hot reload; /api is proxied to :8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

One process instead (what a demo or small deployment wants): `cd frontend && npm run build`, then start only the API. It serves
`frontend/dist` at `/` (deep links like `/chat/C-1` work). Set `FRONTEND_DIR` to serve a build from elsewhere.

Sign in as a customer with any username. The engineer tab needs the passcode (`ENGINEER_PASSCODE`, default `engineer-demo`).
Login is demo-grade (no passwords); do not expose it publicly.

```bash
npm test          # 19 unit/component tests
npm run build     # type-check + production build into dist/
```

## Screens

**Customer**
* **Chat**: starting prompts, menu questions as buttons ("None of these fit" included), a cited fix card (numbered steps with
  `[E1]` chips, a Sources list that marks **Official docs** vs **Community answer** with its licence), "That fixed it / Still not
  working" buttons, then a feedback box (stars, thumbs, comment). Escalated conversations show a banner and the engineer's replies
  (polled every 3 s). Out-of-scope requests show a plain explanation. Customers never see gate scores or internal notes.
* **History**: status, start time, time taken, feedback; opens the full conversation.

**Engineer**
* **Dashboard**: conversations, resolved by agent, resolution rate, escalated (open), out of scope, time to resolution, rating,
  LLM cost; conversations over time; why conversations were escalated; agent behaviour (questions per conversation, cache hit
  rate, verification drops, gate score). Hover a tile for its definition.
* **Escalated cases / All cases**: filter by status, priority, reason, assignee, text; sorted by priority then age; refreshes every 10 s.
* **Case view**: the conversation, reply box, **Resolve** (with an optional "flag for reuse"), reopen; priority and assignment;
  *why the agent escalated* (reason, evidence-gate score and notes, Clarifier verdict, suggested next checks); the ranked causes the
  agent considered; every fix it tried with what each cited and the customer's reply; the last evidence retrieved; the **agent
  activity** timeline from the stored event log; tokens and cost for this case; internal notes (never shown to customers) and an
  audit trail.
* **Analytics** and **Tokens & cost**: outcome charts, escalation reasons, definitions; cost per day, by model and by step, with a
  clear banner when calls used a model that has no price (those are excluded from totals, never counted as free).

## Notes

* Scores are shown as "gate score" and labelled "a heuristic, not a probability" because the thresholds behind them are uncalibrated.
* Charts are in the engineer bundle only (lazy-loaded), so customers do not download them.
* Layout is desktop-first but collapses to a top bar and scrolling tables on narrow screens.
* Not done: attachments, push updates (it polls), dark mode, i18n, end-to-end browser tests (the UI was checked by hand against the
  running backend; the unit tests cover formatting, the API client, the message cards and login).
