#!/bin/bash
# 棱镜进程守护脚本 v2 — 每60秒检查一次，挂了自动重启
API_DIR="/app/data/所有对话/主对话/prism-deploy/prism-api"
LOG="/tmp/prism_guard.log"
TUNNEL_URL_FILE="/tmp/prism_tunnel_url"
RESTART_COUNT=0
MAX_RESTARTS=10

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> $LOG; }

while true; do
    if ! curl -s -m3 http://127.0.0.1:8900/health > /dev/null 2>&1; then
        RESTART_COUNT=$((RESTART_COUNT + 1))
        if [ $RESTART_COUNT -gt $MAX_RESTARTS ]; then log "API restart limit reached"; break; fi
        log "API down (restart #$RESTART_COUNT)"
        pkill -9 -f "uvicorn prism_api" 2>/dev/null; sleep 2
        rm -rf ${API_DIR}/__pycache__
        cd $API_DIR && nohup python3 -m uvicorn prism_api:app --host 0.0.0.0 --port 8900 > /tmp/prism_api.log 2>&1 &
        sleep 5
        if curl -s -m3 http://127.0.0.1:8900/health > /dev/null 2>&1; then log "API restart OK"; RESTART_COUNT=0; fi
    else
        RESTART_COUNT=0
    fi
    if ! pgrep -x cloudflared > /dev/null 2>&1; then
        log "Cloudflared down, restarting"
        nohup cloudflared tunnel --url http://localhost:8900 > /tmp/cloudflared.log 2>&1 &
        sleep 10
        NEW_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | tail -1)
        [ -n "$NEW_URL" ] && echo "$NEW_URL" > $TUNNEL_URL_FILE && log "New tunnel: $NEW_URL"
    fi
    MINUTE=$(date +%M)
    if [ "$MINUTE" = "00" ] || [ "$MINUTE" = "30" ]; then
        HEALTH=$(curl -s -m5 http://127.0.0.1:8900/health 2>/dev/null)
        echo "$HEALTH" | grep -q '"degraded"' && log "DEGRADED: $HEALTH"
    fi
    sleep 60
done
