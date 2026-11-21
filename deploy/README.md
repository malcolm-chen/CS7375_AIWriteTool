# Deploying on the lab machine

One machine runs everything. FastAPI serves the API and the built frontend on `127.0.0.1:8000`. Public HTTPS comes from **Cloudflare Tunnel** (no open ports needed) or from **Caddy** (if university IT gives the machine a public hostname). HTTPS is required for the microphone and for the admin cookie in production mode.

Run a single server process. Balanced assignment relies on one SQLite file and a write lock, so don't run multiple workers or a second machine against copies of the database.

These steps assume Ubuntu (or another Linux with systemd), the repo at `/srv/cowrite`, and a user named `cowrite`. If you use another path or user, change them in `cowrite.service` and `cowrite-backup.service`.

## 1. Prerequisites

```bash
sudo apt update && sudo apt install -y git python3 python3-venv curl
# Node.js 18 or newer, for building the frontend (or install it with nvm):
sudo apt install -y nodejs npm && node --version
```

Turn off sleep, so the server stays up:

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

## 2. Get the code

```bash
sudo useradd --system --create-home --shell /bin/bash cowrite
sudo mkdir -p /srv/cowrite && sudo chown cowrite: /srv/cowrite
sudo -iu cowrite
git clone https://github.com/malcolm-chen/CS7375_AIWriteTool.git /srv/cowrite
cd /srv/cowrite
```

The `cowrite` user needs sudo for the next step, to install the systemd units. Otherwise run those lines of `install.sh` from an admin account.

## 3. Configure

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # use this as COWRITE_SECRET
```

Edit `backend/.env`:

| Setting | Value |
|---|---|
| `COWRITE_PRODUCTION` | `1` |
| `COWRITE_SECRET` | the random string from above |
| `COWRITE_ADMIN_PASSWORD` | a strong password, at least 12 characters, shared only with the researchers |
| `COWRITE_DEMO` | `0` |
| `OPENAI_API_KEY` / `KIMI_API_KEY` | the study's keys |
| `OPENAI_TIMEOUT` / `KIMI_TIMEOUT` | `40` if you use Cloudflare Tunnel (see "Timeouts" below) |

With `COWRITE_PRODUCTION=1`, the server refuses to start while the default password or secret is still in place, or while demo mode is on.

## 4. Install and start

```bash
./deploy/install.sh
```

This script:
- creates the Python environment and runs the backend tests
- builds the frontend
- installs and starts `cowrite.service`, which restarts the server automatically
- installs `cowrite-backup.timer`, which backs up the database daily

Re-run it after every `git pull` to update.

Useful commands:

```bash
systemctl status cowrite
journalctl -u cowrite -f            # live logs
sudo systemctl restart cowrite      # after editing backend/.env
```

## 5. Public HTTPS

### Option A: Cloudflare Tunnel (no open ports, works behind the campus firewall)

You need a free Cloudflare account and a domain managed by Cloudflare, either one you already have or a new one (about $10 a year). Install `cloudflared` by following [Cloudflare's instructions](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/), then:

```bash
cloudflared tunnel login
cloudflared tunnel create cowrite
cloudflared tunnel route dns cowrite study.example.com
```

Create `~/.cloudflared/config.yml`. `tunnel create` prints the tunnel id and the path of its credentials file.

```yaml
tunnel: <tunnel id>
credentials-file: /home/cowrite/.cloudflared/<tunnel id>.json
ingress:
  - hostname: study.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Then run it as a service: `sudo cloudflared --config /home/cowrite/.cloudflared/config.yml service install`.

For a quick pilot with no domain, `cloudflared tunnel --url http://127.0.0.1:8000` prints a temporary `trycloudflare.com` address. That address changes every time it restarts, so don't use it for real participants.

### Option B: Caddy (if IT gives you a public hostname with ports 80 and 443 open)

Install Caddy ([instructions](https://caddyserver.com/docs/install)). Put your hostname in `deploy/Caddyfile`, then:

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

Caddy gets and renews the HTTPS certificate itself.

## Timeouts

"Revise with AI" holds the request open until the model answers, which usually takes well under a minute. Cloudflare closes requests after about 100 seconds. If a provider fails, it is retried once and then the next provider is tried, so a slow failure can take longer than that. Set `OPENAI_TIMEOUT`/`KIMI_TIMEOUT` to about 40 seconds to stay mostly within the limit.

If a participant still sees an error after a long wait, the server has usually kept going and finished the revision. Ask them to wait a minute and reload the page: they will land in the review step. The `enhance_done` / `enhance_fail` events in the export show what happened. Caddy (Option B) is configured not to time out.

## Backups

`cowrite-backup.timer` runs `deploy/backup.py` daily at 03:30. Each run writes a consistent copy to `backend/data/backups/` and keeps the latest 30.

To back up by hand, e.g. right before a session: `backend/.venv/bin/python deploy/backup.py`.

**Copy the backups off the machine regularly**, for example to university storage approved for study data. A backup on the same disk doesn't help if that disk fails. To restore, stop the server, copy a backup over `backend/data/cowrite.db`, then start the server again.

## Updating

When new code is merged to `main`:

```bash
sudo -iu cowrite
cd /srv/cowrite
backend/.venv/bin/python deploy/backup.py      # back up first
git pull
./deploy/install.sh                            # tests, rebuild, restart
```

If participants are mid-session, avoid updating. A restart takes a few seconds and drafts are saved, but a request that is running at that moment (such as "Revise with AI") fails and has to be retried.

## Troubleshooting

| Symptom | Check |
|---|---|
| Site doesn't load / Cloudflare 502 | `systemctl status cowrite`, then `journalctl -u cowrite -n 50`. Is the server running on `127.0.0.1:8000`? Try `curl http://127.0.0.1:8000/api/auth/me` on the machine. |
| Server won't start: "COWRITE_PRODUCTION is on, but …" | The message lists what to fix in `backend/.env`: the default password or secret, a value that's too short, or demo mode left on. Fix it, then `sudo systemctl restart cowrite`. |
| "Revise with AI" fails for everyone | The admin page says whether an AI provider is configured. Check the API keys in `backend/.env`. The `enhance_fail` events in the export include the provider's error message. |
| "Revise with AI" fails only after about 100 s | The Cloudflare timeout (see "Timeouts" above). Lower `<NAME>_TIMEOUT`. |
| Microphone doesn't work | The page must be opened over HTTPS, in Chrome or Edge. Other browsers fall back to typing. |
| Edited `backend/.env` but nothing changed | Restart: `sudo systemctl restart cowrite`. |
| A participant's link says "not valid" | The link was regenerated ("New link" on `/admin`), or it was copied incompletely. Send them the current link from their "Task 1" row. |

## Before the first real participant

- [ ] `https://<your host>/admin` loads, and you can log in with the new password.
- [ ] Create a test participant on `/admin`, open their link on a phone (off the lab network), and go through both tasks:
  - write a draft
  - revise with AI
  - confirm an edit, and correct one by voice and one by typing
  - click Next task
- [ ] The Balance card shows the test participant. Delete them afterwards so they don't count toward balance.
- [ ] `systemctl list-timers cowrite-backup.timer` shows the next backup, and `deploy/backup.py` succeeds when run by hand.
- [ ] Reboot the machine and check that the site comes back up by itself.
