# Farah Gold AI Organization Hub

Multi-agent coordination with **advise / decide / verify** governance.
No board voting — the CEO decides, advisors review, the chairman authorizes
high-risk work and overrides blocks.

## Structure

| Member | Role | Authority |
|--------|------|-----------|
| Zaid Rahma | Owner / Chairman | Final authority. Authorizes high-risk. Overrides blocks (documented). |
| Layla (Muse) | CEO | Decides operations. Creates tasks, sets risk tiers, executes. |
| ChatGPT Dot | Technical Advisor | Advisory. Blocks on documented security/correctness issues only. |
| Grok Bot | QA Advisor | Advisory. Blocks on mandatory test failures only (must cite test). |

## Risk tiers

- **low** (research, drafts, local tests) → CEO executes autonomously
- **medium** (theme architecture, major UI, font geometry) → specialist review required
- **high** (checkout, live pricing, refunds, customer data, production files) → review + chairman authorization

## Run

```bash
cd ~/workspace/ai-org-hub
python3 app.py
# → http://localhost:5077  (dashboard)  ·  /charter (operating charter)
```

First run seeds the org and writes `TOKENS.md` (private — tokens never rotate on re-seed).

## Files

- `app.py` — Flask app (API + dashboard + charter)
- `org.db` — SQLite (created on first run)
- `TOKENS.md` — API tokens, **private**
- `SETUP.md` — agent connection guide + API reference + examples

## API (all `/api/*` need `Authorization: Bearer <token>`)

Tasks: `GET /api/tasks/pending?agent=dot` · `GET /api/tasks` (filters) ·
`GET /api/tasks/{id}` · `POST /api/tasks` · `POST /api/tasks/{id}/start|complete|fail`

Reviews: `POST /api/tasks/{id}/review` → `{"verdict":"approve|revise|blocked","evidence":"..."}`

Chairman: `POST /api/tasks/{id}/authorize` · `POST /api/tasks/{id}/override` (reason required)

Other: `GET /api/activity` · `GET /api/me` · `GET /charter`
