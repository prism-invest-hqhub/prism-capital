#!/bin/bash
# 棱镜进程守护脚本 — 每60秒检查一次，挂了自动重启
API_DIR="/app/data/所有对话/主对话/prism-deploy/prism-api"
LOG="/tmp/prism_guard.log"

while true; do
    # 检查API
    if ! curl -s -m3 http://127.0.0.1:8900/health > /dev/null 2>&1; then
        echo "[$(date)] API down, restarting..." >> $LOG
        pkill -f "uvicorn prism_api" 2>/dev/null
        sleep 1
        rm -rf ${API_DIR}/__pycache__
        cd $API_DIR && nohup python3 -m uvicorn prism_api:app --host 0.0.0.0 --port 8900 > /tmp/prism_api.log 2>&1 &
        echo "[$(date)] API restarted, PID=$!" >> $LOG
    fi
    
    # 检查cloudflared
    if ! pgrep -x cloudflared > /dev/null 2>&1; then
        echo "[$(date)] Cloudflared down, restarting..." >> $LOG
        nohup cloudflared tunnel --url http://localhost:8900 > /tmp/cloudflared.log 2>&1 &
        echo "[$(date)] Cloudflared restarted, PID=$!" >> $LOG
    fi
    
    sleep 60
done
