#!/bin/bash
# Auto-deploy script for Klimadashboard API
# Pulls latest code from GitHub and rebuilds if changed.
#
# Usage:
#   ./deploy.sh              # Run once
#   crontab: */5 * * * *     # Run every 5 minutes via cron
#
# Setup (run once on server):
#   cd /opt/klimadashboard-api
#   git clone https://github.com/klimadashboard/api.git .
#   cp .env.example .env     # edit with your values
#   chmod +x deploy.sh
#   docker compose up -d --build

set -e

DEPLOY_DIR="/opt/klimadashboard-api"
LOG_FILE="/var/log/klimadashboard-api-deploy.log"

cd "$DEPLOY_DIR"

# Fetch latest changes
git fetch origin main --quiet

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    # No changes — exit silently (don't spam the log)
    exit 0
fi

# New commits found — pull and rebuild
echo "[$(date -Iseconds)] Deploying $LOCAL → $REMOTE" >> "$LOG_FILE"

git pull origin main --quiet

docker compose up -d --build --quiet-pull >> "$LOG_FILE" 2>&1

echo "[$(date -Iseconds)] Deploy complete" >> "$LOG_FILE"
