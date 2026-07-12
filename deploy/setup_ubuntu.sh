#!/usr/bin/env bash
# Run once on a fresh Ubuntu 22.04+ server to install Docker and start the daemon.
# Must be run as root (or with sudo).
set -euo pipefail

echo "=== Novax Production Setup ==="

# 1. Install Docker
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. Create app directory and copy project
APP_DIR="/opt/novax"
mkdir -p "${APP_DIR}/data" "${APP_DIR}/logs"
echo "App directory: ${APP_DIR}"

# NOTE: Copy project files to ${APP_DIR} before continuing:
#   scp -r /path/to/novax-research/* user@server:${APP_DIR}/
# Or clone from git:
#   git clone <repo-url> ${APP_DIR}

# 3. Verify .env exists with required vars
cd "${APP_DIR}"
if [ ! -f .env ]; then
    echo ""
    echo "ERROR: .env file not found."
    echo "  cp .env.example .env"
    echo "  # then edit .env with your credentials"
    exit 1
fi

for VAR in TWELVEDATA_API_KEY TELEGRAM_TOKEN TELEGRAM_CHAT_ID; do
    if ! grep -q "^${VAR}=" .env; then
        echo "ERROR: ${VAR} is not set in .env"
        exit 1
    fi
done

# 4. Build Docker image and start daemon
docker compose build
docker compose up -d prod-daemon
echo ""
echo "Daemon started."

# 5. Add cron job for Sunday 21:00 UTC weekly analysis
CRON_CMD="0 21 * * 0 cd ${APP_DIR} && docker compose --profile weekly run --rm weekly-analysis >> ${APP_DIR}/logs/weekly_analysis.log 2>&1"
(crontab -l 2>/dev/null | grep -v "weekly-analysis" ; echo "${CRON_CMD}") | crontab -
echo "Weekly analysis cron installed (Sunday 21:00 UTC)."

echo ""
echo "=== Setup complete ==="
echo "Monitor daemon : docker logs -f novax-prod-daemon"
echo "Tail log file  : tail -f ${APP_DIR}/logs/daemon_XAUUSD.log"
echo "Run weekly now : cd ${APP_DIR} && docker compose --profile weekly run --rm weekly-analysis"
