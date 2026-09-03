#!/usr/bin/env bash
# Serve the Broker Content Engine on port 3000 so it shows up at the platform
# preview URL. This repo has no /app/frontend or /app/backend, so the default
# supervisor programs are FATAL and nothing serves the preview by default.
#
# Re-run this after a pod restart if the preview goes blank:
#   bash /app/scripts/enable_preview.sh
set -euo pipefail

# The package must be importable (editable install). Reinstall if missing.
/root/.venv/bin/python -c "import bce" 2>/dev/null || /root/.venv/bin/pip install -e /app >/dev/null

# Ensure a database exists to serve.
[ -f /app/bce.db ] || ( cd /app && /root/.venv/bin/bce init && /root/.venv/bin/bce seed-example )

cp /app/scripts/bce.supervisor.conf /etc/supervisor/conf.d/bce.conf
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart bce || sudo supervisorctl start bce
sleep 3
sudo supervisorctl status bce
curl -s -o /dev/null -w "local  GET / -> %{http_code}\n" http://127.0.0.1:3000/
echo "Preview served on :3000"
