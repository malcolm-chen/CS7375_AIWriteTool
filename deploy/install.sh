#!/usr/bin/env bash
# First-time setup and updates on the lab machine. Run from the repo root as the "cowrite" user:
#   ./deploy/install.sh
# Safe to re-run after `git pull`: rebuilds and restarts.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f backend/.env ] || { echo "Create backend/.env first (cp backend/.env.example backend/.env, then edit). See deploy/README.md."; exit 1; }
grep -q '^COWRITE_PRODUCTION=1' backend/.env || echo "warning: COWRITE_PRODUCTION=1 is not set in backend/.env"

echo "== backend"
[ -d backend/.venv ] || python3 -m venv backend/.venv
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements.txt
mkdir -p backend/data
(cd backend && .venv/bin/python -m pytest -q -p no:warnings)

echo "== frontend"
(cd frontend && npm ci --silent && npm run build)

echo "== services"
if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
  echo "Installing the systemd units needs sudo:"
fi
sudo cp deploy/cowrite.service deploy/cowrite-backup.service deploy/cowrite-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cowrite-backup.timer
sudo systemctl enable cowrite
sudo systemctl restart cowrite
sleep 2
curl -fsS http://127.0.0.1:8000/api/auth/me >/dev/null && echo "CoWrite is running on 127.0.0.1:8000" \
  || { echo "CoWrite did not start; see: journalctl -u cowrite -n 50"; exit 1; }
