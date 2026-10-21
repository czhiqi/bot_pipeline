# FORGE: strategy pipeline web app

Built on the Nova template (Next.js 16, MySQL + Drizzle, email/password sessions, EN / 中文). The video studio is replaced by a strategy workspace connected to one GitHub repo:

**Hypothesis → (Gemini beautify) → strategy.py (OpenRouter or upload) → risk config → commit → GitHub Actions gates → pull request → download bot**

The site never holds exchange keys and never trades. Backtests and gates run in **your repo's GitHub Actions**. The site reads the report.

## How it fits together

| Piece | Where | What it does |
|---|---|---|
| Workspace | this app | One strategy = branch `strategy/<slug>` = folder `bots/<slug>/` |
| Beautify | Gemini (`GEMINI_API_KEY`) | Rewrites a rough hypothesis into precise, testable rules and lists open questions. Never invents results |
| Generate | OpenRouter (`OPENROUTER_API_KEY`) | Writes or revises `strategy.py` against the engine interface; can take the last failed gate result as feedback |
| Upload | browser | `strategy.py`, `config.json`, `hypothesis.md`, or a candle `.csv` (committed to `data/`) |
| Commit | GitHub API | One commit with the three bot files (+ data). The push starts the workflow |
| Gates | GitHub Actions (`repo-template/.github/workflows/pipeline.yml`) | Code check, risk, backtest, out-of-sample, drawdown, live = backtest parity. Uploads `pipeline-report` |
| Review | GitHub PR | "Submit for review" opens `strategy/<slug> → main` with the gate summary and a checklist |
| Deploy | zip download | `engine/`, `bots/<slug>/`, `run_bot.py`, `.env.example`, `DEPLOY.md`, `BOT.txt` from the exact commit |

Status flow: `draft → testing → passed | failed → submitted → merged`. Editing after a commit shows "unsaved changes"; you must commit again before you can submit.

## Setup

1. **Repo:** copy everything in `repo-template/` into your GitHub repo's `main` branch (see `repo-template/DEPLOY.md` → Repository setup: CODEOWNERS and branch protection).
2. **Token:** create a fine-grained GitHub token for only that repo with *Contents: read & write*, *Pull requests: read & write*, *Actions: read*.
3. **App:**
   ```bash
   npm install
   cp .env.example .env          # fill in every value
   npm run db:init               # creates users, strategies, ai_calls (MySQL 5.6.5+/5.7/8)
   npm run dev
   ```
4. Sign in with an email listed in `ADMIN_EMAILS` and open **/admin**. The connection check confirms the token, base branch, workflow file and engine are in place.

Production: `npm run build && npm start` behind nginx or Caddy with TLS. Allow request bodies of at least `MAX_DATA_MB` + 1 MB on `/api/strategies/*/commit` (CSV uploads), and rate-limit `/api/auth/*`.

## Users who submit strategies

- Each non-admin user sees only their own strategies. Admins see everyone's (`/workspace?all=1`) and can download any committed version.
- Limits per user (env): AI calls per hour, strategies per user, commits per hour.
- Submitted code is checked twice: instantly in the browser and before commit (`lib/pipeline.ts quickCheck`), then by the AST check in CI (`engine/sandbox_check.py`). The two agree on the test corpus. **Neither is a sandbox.** Safety comes from CI having no secrets and read-only repo access, code-owner review before merge, and paper trading before live keys.
- Gate thresholds live in `pipeline.json` on `main` (code-owner protected). A branch that changes anything outside `bots/` and `data/` fails the "Only bots/ changed" gate.

## Structure

```
app/
  page.tsx                      landing
  workspace/                    strategy list + new branch form (components/WorkspaceList.tsx)
  workspace/[id]/               editor: hypothesis, code, risk, gates, review, deploy (components/Editor.tsx)
  admin/                        connections, stats, all strategies
  api/strategies                GET list · POST create (creates the branch)
  api/strategies/[id]           GET (polls GitHub) · PATCH save draft · DELETE (archive + delete branch)
  api/strategies/[id]/beautify  POST → Gemini
  api/strategies/[id]/generate  POST → OpenRouter
  api/strategies/[id]/commit    POST multipart → GitHub commit (starts gates)
  api/strategies/[id]/submit    POST → pull request
  api/strategies/[id]/download  GET → deploy zip
lib/
  github.ts      GitHub REST: branches, atomic multi-file commits, Actions runs + artifacts, PRs, deploy zip
  gemini.ts      beautify (strict JSON schema)
  openrouter.ts  code generation (+ STRATEGY_GUIDE in templates.ts)
  pipeline.ts    shared types, config validation, browser code check
  strategies.ts  loading, status refresh from GitHub, file hashing
db/schema.ts, db/init.sql   users, strategies, ai_calls
```

## Model notes

- `OPENROUTER_MODELS` is a comma list shown in the editor. `~anthropic/claude-opus-latest` always points to the newest Claude Opus. Add others by their OpenRouter IDs.
- `GEMINI_MODEL` defaults to the template's `gemini-3.8-flash`.
