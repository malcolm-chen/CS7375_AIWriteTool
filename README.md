# CoWrite: Revision Review

A study tool for comparing what an AI says it changed with what the writer meant.

Each participant writes **two short high-stakes emails**: negotiating the salary of their first job offer, and apologizing to a professor who vouched for them. For each one:

1. **Write.** The participant reads the scenario and writes their own draft without AI help. Spellcheck is off.
2. **Review.** "Revise with AI" sends the draft to an LLM, which revises it and explains each change. The participant sees their original and the revision side by side, with every change highlighted except grammar and spelling fixes. They go through the changes one by one and either confirm each one ("Matches what I meant") or say or type what they actually meant.

One of the two tasks shows the AI's explanation for each change. The other shows a neutral question in the same place instead. The task order and which task gets explanations are randomized per participant, and balanced across participants (see [Study design](#study-design)).

`SPEC.md` and `prototype.html` are the original spec and visual reference. The study design has since moved on from them, and this README describes the current system.

## Contents

- [Run it locally](#run-it-locally)
- [Host it for the study](#host-it-for-the-study)
- [Run a study](#run-a-study)
- [Configuration](#configuration)
- [Study design](#study-design)
- [How revisions work](#how-revisions-work)
- [Data](#data)
- [Tests](#tests)
- [Not implemented yet](#not-implemented-yet)

## Run it locally

You need Python 3.10+ and Node.js 18+.

```bash
# 1. Backend (http://localhost:8000)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # then add an OPENAI_API_KEY and/or KIMI_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000

# 2. Frontend dev server, in a second terminal (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173/admin and log in with `COWRITE_ADMIN_PASSWORD` (default `admin`). To try the participant side without creating sessions, set `COWRITE_DEMO=1` in `backend/.env` and open http://localhost:5173/demo.

To run everything from one server, run `npm run build` in `frontend/`. FastAPI then serves the built site on :8000 as well.

## Host it for the study

The whole app is **one Python process**. FastAPI serves both the API and the built frontend, and all data lives in **one SQLite file**. Hosting it means running that process on a machine that stays on, with HTTPS in front.

```
participant's browser ──HTTPS──▶ Cloudflare Tunnel or Caddy ──▶ uvicorn on 127.0.0.1:8000 ──▶ backend/data/cowrite.db
                                                                        │
                                                                        └──▶ OpenAI / Kimi API
```

We host it on a **lab machine running Linux**. The full step-by-step guide is [`deploy/README.md`](deploy/README.md). In short:

1. **Prepare the machine:** install git, Python 3 and Node.js, turn off sleep, create a `cowrite` user, and clone this repo to `/srv/cowrite`.
2. **Configure:** copy `backend/.env.example` to `backend/.env`. Set `COWRITE_PRODUCTION=1`, a random `COWRITE_SECRET`, a strong `COWRITE_ADMIN_PASSWORD`, `COWRITE_DEMO=0`, and the API keys.
3. **Install:** run `./deploy/install.sh`. It does four things:
   - sets up the Python environment
   - runs the tests
   - builds the frontend
   - installs two systemd units: one keeps the server running and starts it on boot, the other backs up the database daily
4. **Make it public over HTTPS.** HTTPS is required for the microphone.
   - **Cloudflare Tunnel** if the machine is behind the campus firewall (no ports to open).
   - **Caddy** if university IT gives the machine a public hostname.
5. **Check it:** go through the "Before the first real participant" checklist at the end of `deploy/README.md`, including a full run-through on a phone off the lab network.

To **update** the live site, run `git pull && ./deploy/install.sh` on the machine. The script rebuilds and restarts.

Things to keep in mind:

- **Run exactly one server process.** Balanced assignment relies on a single SQLite file and a write lock. Don't add workers, and don't run a second copy of the app against a copy of the database.
- **Platforms without a persistent disk or with short request timeouts don't fit.** On Heroku, for example, dynos restart daily and lose local files, and requests are cut off at 30 s. "Revise with AI" can take longer than that.
- **Back up off the machine.** The daily backups land in `backend/data/backups/`. Copy them somewhere else regularly, ideally university storage approved for study data.
- **For a quick pilot with teammates,** run the app on your laptop and expose it with `cloudflared tunnel --url http://127.0.0.1:8000`. That prints a temporary public HTTPS address, which changes on every restart, so don't use it for real participants.

## Run a study

1. **Create participants.** On `/admin`, enter participant IDs (e.g. `P01, P02`) and click Create. Leave the task on **"All 2 tasks, random order"**. Each participant gets two linked sessions. Send each person the link from their **"Task 1"** row. After they review task 1, a "Next task" button takes them to task 2. From the command line: `cd backend && .venv/bin/python -m app.cli create P01 P02`.
2. **Watch the balance.** The "Balance" card shows how many participants are completed, in progress or abandoned for each of the four assignments, and for each task × condition. Each row in the session list shows that participant's status.
3. **Export.** Use "Export all JSON/CSV" at the top of `/admin`, or the JSON/CSV buttons on a single row.

Other admin actions:

- **Open:** view a session as the researcher (with the "Study settings" panel). Viewing as admin never assigns the participant or follows their "Next task" link.
- **New link:** replaces the participant's link. The old one stops working.
- **Reset:** clears that session's decisions and events and returns it to an empty draft. The task assignment and its `assigned` event are kept.
- **Delete:** removes the participant, with all of their tasks and data.
- **Pilot a single task:** choose "Only: …" and a condition. This creates one standalone session that doesn't count toward balance.
- **Import:** load pre-generated revisions to skip the writing step (see [Import format](#import-format)).

Before the study, delete any test participants so they don't count toward balance.

## Configuration

Settings go in `backend/.env` (template: `backend/.env.example`). Restart the server after editing it (`sudo systemctl restart cowrite` on the lab machine).

| Variable | Default | |
|---|---|---|
| `LLM_PROVIDERS` | `openai,kimi` | Providers tried in order. If one fails (after one retry), the next is used. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | (none) / `gpt-6-sol` | Primary |
| `KIMI_API_KEY` / `KIMI_MODEL` / `KIMI_BASE_URL` | (none) / `kimi-k3` / `https://api.moonshot.ai/v1` | Fallback |
| `<NAME>_REASONING_EFFORT`, `<NAME>_TEMPERATURE`, `<NAME>_TIMEOUT` | unset, unset, 180 s | Optional, per provider. Use a timeout of about 40 s behind Cloudflare Tunnel. |
| `COWRITE_ADMIN_PASSWORD` | `admin` | Researcher login |
| `COWRITE_SECRET` | `dev-secret-change-me` | Signs the admin cookie |
| `COWRITE_PRODUCTION` | `0` | `1` on the deployed server. The admin cookie is then sent over HTTPS only, and the server won't start with the default password or secret, or with demo mode on. |
| `COWRITE_DEMO` | `0` | `1` enables `/demo`, which creates a throwaway participant without logging in. Demo sessions never count toward balance. |
| `COWRITE_ABANDON_HOURS` | `24` | A participant who started this long ago without finishing no longer counts toward balance |
| `COWRITE_DB` | `backend/data/cowrite.db` | SQLite file |

## Study design

- **Tasks** live in `backend/app/tasks.py`. Each has a title, scenario, assignment and a minimum word count (40).
  - `salary_negotiation`: reply to your first full-time offer and ask for a higher salary, without risking the offer.
  - `professor_apology`: apologize to a professor who set up an internship introduction you missed.
- **Conditions** (`STUDY_CONDITIONS` in `tasks.py`). Every participant writes every task in `STUDY_TASKS`, one in each condition:
  - `reasons`: hovering a change shows the AI's explanation, under the label "Why the AI made this change".
  - `noReasons`: the same box, labeled "Check this edit", shows "Does this edit match what you meant?" instead.

  Everything else is identical in the two conditions, including confirming or correcting every change. In `noReasons` the server leaves the explanations out of what it sends, so they never reach the browser. They are still generated, stored and exported.
- **Balance** (`backend/app/assignment.py`).
  - Task order × which task gets explanations gives 2 × 2 = 4 assignments.
  - A participant is assigned **when they first open their link**, so links nobody opens take no slot.
  - They get a random choice among the assignments with the fewest participants still in the study, which keeps the four within one of each other.
  - "Still in the study" means completed, or started less than `COWRITE_ABANDON_HOURS` ago. Completed means every task is in review and every highlighted change has a decision.
  - Anyone who started earlier and hasn't finished counts as abandoned, and their slot goes to the next participant. If an abandoned participant comes back and finishes, they count again, so a cell can end up one over.
  - Assignment takes a database write lock, so simultaneous first opens stay balanced. Demo sessions never count.
- **Links.** Each participant's link is `/session/:id?t=<token>`. The server sends the link to the next task only to the participant, and only after the current task has reached review.

## How revisions work

- **Prompts** live in `backend/app/llm.py`. Each prompt has a version id, which is stored with every explanation.
  - `ENHANCE_SYSTEM` (`enhance-v3`) asks the model to revise the draft at the word and phrase level so it better accomplishes the task. It returns the full revision plus every change. Each change carries its exact fragments, a type (`grammar` or `content`), and a one-sentence explanation addressed to the writer.
  - `EXPLAIN_SYSTEM` (`explain-v1`) classifies and explains changes the model left out of its own list. These explanations are stored with `mode: "post_hoc"`; self-explanations use `mode: "self"`.
- **Edits are computed by the system.** The model's reported fragments aren't reliably exact. So the system runs its own word-level diff on the two texts, then maps each diff span to the model's changes by position. Spans covered by the same reported change share its explanation.
- **Grammar-only changes** are applied but not highlighted or reviewed.
- **Errors.** A response that isn't valid JSON is retried once, then the next provider is tried. If the revision still fails, the participant goes back to the writing step with a "Try again" button. The session's `meta` stores:
  - the raw model response
  - the provider and model that answered (e.g. `openai:gpt-6-sol`)
  - any fallback errors
  - the latency

## Data

- **Events** carry the stage, the actor (`participant` or `admin`), and both client and server timestamps:
  - Assignment: `assigned`, with the task order and conditions. The server writes it on first open.
  - Writing step: `session_start`, `writing_start`, `draft_submit`, `enhance_done`, `enhance_fail`. The client also sends `paste` events, which the server intentionally doesn't store.
  - Review step: `view`, `pin`, `unpin`, `confirm`, `correct_start`, `correct_submit`, `correct_redo`, `correct_fail`, `undo`, `next_task`, `session_end`.
- **Decisions:** one per reviewed change, either `confirmed` or `corrected`. A correction includes its text and modality (`voice` or `text`).
- **JSON export:** the task, condition, assignment, draft, revision, edits (with kind and explanation, including in `noReasons`), the model's raw response, decisions and events.
- **CSV export:** one row per event, with the edit's text, kind and explanation joined in. `group_id`, `task_seq` and `condition` identify each participant's task order and condition.

### Import format

Accepted shapes: a list of records, `{"items": [...]}`, or an object keyed by record id.

- Each record has `original` and `revised`, plus optional `participantId`, `taskId` and `edits`.
- Each edit is `{original, revised, explanation, kind}`. `kind: "grammar"` means the edit isn't highlighted.
- If the edits don't line up with the texts, or are missing, a word-level diff is computed instead.

See `sample_data/sample_revisions.json`. Imported sessions start at the review step and don't count toward balance.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npx tsc --noEmit -p .
```

## Not implemented yet

- A break or questionnaire page between the two tasks (discussed in #2), and a closing page such as a completion code.
- Server-side speech recognition. Voice uses the browser's Web Speech API (Chrome and Edge). Other browsers offer typing only, and audio isn't stored.
- Per-researcher admin accounts. There is one shared admin password.
- The interface is English only.
