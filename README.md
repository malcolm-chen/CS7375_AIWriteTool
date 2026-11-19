# CoWrite: Revision Review

A study tool for comparing what an AI says it changed with what the writer meant. Each participant goes through two steps:

1. **Write.** The participant reads a predefined high-stakes writing task (an email to a hiring manager about a job opening) and writes their own draft without AI help. Spellcheck is turned off in the text box.
2. **Review.** "Revise with AI" sends the draft to Kimi, which revises it and explains each change. The participant then sees the original and the revision side by side. Every change except grammar and spelling fixes is highlighted. Hovering a highlight shows the AI's explanation. The participant confirms each change, or says or types what they actually meant.

`SPEC.md` and `prototype.html` are the original spec and visual reference.

## Run

```bash
# backend (http://localhost:8000)
cd backend
uv venv .venv && uv pip install -p .venv -r requirements.txt   # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# frontend dev server (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

For a single-server setup, run `npm run build` in `frontend/`. FastAPI then serves `frontend/dist` on :8000.

Settings go in `backend/.env` (template: `backend/.env.example`). Restart the backend after you edit it.

| Variable | Default | |
|---|---|---|
| `LLM_PROVIDERS` | `openai,kimi` | Providers tried in order. If one fails (after one retry), the next is used. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | (none) / `gpt-6-sol` | Primary |
| `KIMI_API_KEY` / `KIMI_MODEL` / `KIMI_BASE_URL` | (none) / `kimi-k3` / `https://api.moonshot.ai/v1` | Fallback |
| `<NAME>_REASONING_EFFORT`, `<NAME>_TEMPERATURE`, `<NAME>_TIMEOUT` | unset, unset, 180 s | Optional, per provider |
| `COWRITE_ADMIN_PASSWORD` | `admin` | Researcher login. Change it before running a study. |
| `COWRITE_SECRET` | `dev-secret-change-me` | Signs the admin cookie |
| `COWRITE_DB` | `backend/data/cowrite.db` | SQLite file |

## Tasks and prompts

- **Tasks** live in `backend/app/tasks.py`. Each task has a title, scenario, job posting, instructions and a minimum word count (60). Add another task as a new entry in that file.
- **Prompts** live in `backend/app/llm.py`. Each prompt has a version id, which is stored with every explanation.
  - `ENHANCE_SYSTEM` (`enhance-v1`) asks the model to revise the draft so it better accomplishes the task, and to return the full revision plus every change. Each change carries its exact fragments, a type (`grammar` or `content`), and a one-sentence explanation addressed to the writer.
  - `EXPLAIN_SYSTEM` (`explain-v1`) classifies and explains changes the model left out of its own list. These explanations are stored with `mode: "post_hoc"`; self-explanations use `mode: "self"`.
- **Edits are computed by the system.** The model's reported fragments aren't reliably exact, so the system runs its own word-level diff on the two texts, then maps each diff span to the model's changes by position. Edits covered by one reported change are merged, and each edit is widened to the change's full extent.
- **Errors and stored output.** A response that isn't valid JSON is retried once. If the revision still fails, the participant goes back to the writing step with a "Try again" button. The raw model response, the provider and model that answered (for example `openai:gpt-6-sol`), any fallback errors, and the latency are stored in the session's `meta`. The same provider:model is stored with every explanation.

## Create sessions

- **Admin page:** go to `/admin`, enter participant IDs, choose a task, then click Create. Copy each participant's link from the table.
- **Command line:** run `cd backend && .venv/bin/python -m app.cli create P01 P02 P03`.

You can still import pre-generated revisions to skip the writing step. Use the "Import" section on the admin page, or `python -m app.cli import file.json`.

## Import format (optional)

Accepted shapes: a list of records, `{"items": [...]}`, or an object keyed by record id. Each record has `original` and `revised`, plus optional `participantId`, `taskId` and `edits`. Each edit is `{original, revised, explanation, kind}`, where `kind: "grammar"` means the edit isn't highlighted. If the edits don't line up with the texts, or are missing, a word-level diff is computed instead. See `sample_data/sample_revisions.json`.

## Admin

- `/admin`: create sessions, import revisions, see each session's stage (writing, AI revising, reviewing), copy participant links, open a session as admin, export one or all sessions (JSON/CSV), regenerate a link, reset, delete.
- **Reset:** clears decisions and events. Task sessions also go back to an empty draft.
- **Access:** participants use `/session/:id?t=<token>`. The backend decides the role from the admin cookie or a valid token.

## Data

- **Events** carry the stage, actor, and both client and server timestamps:
  - Writing step: `session_start`, `writing_start`, `paste` (with character count), `draft_submit`, `enhance_done`, `enhance_fail`.
  - Review step: `view`, `pin`, `unpin`, `confirm`, `correct_start`, `correct_submit`, `correct_redo`, `correct_fail`, `undo`, `session_end`.
- **JSON export:** the task, draft, revision, edits (with kind and explanation), the model's raw response, decisions, and events.
- **CSV export:** one row per event, with the edit's text, kind and explanation joined in.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

## Not implemented yet

- Server-side ASR. Voice uses the Web Speech API (Chrome and Edge). Other browsers fall back to text input. Audio isn't stored.
- One-time participant links. Links can be reused until you regenerate them.
- The interface is English only.
