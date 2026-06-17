#!/bin/bash
# 棱镜守护脚本 v1.0 - 保持API和隧道在线
# 用法: nohup bash prism-guard.sh > /tmp/guard.log 2>&1 &

API_DIR="/app/data/所有对话/主对话/prism-deploy/prism-api"
API_PORT=8900
CHECK_INTERVAL=60

while true; do
    # 检查API是否存活
    if ! curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$API_PORT/health 2>/dev/null | grep -q "200"; then
        echo "[$(date)] API down, restarting..."
        # 杀死旧进程
        lsof -ti :$API_PORT | xargs kill -9 2>/dev/null
        sleep 2
        cd $API_DIR && nohup python3 -m uvicorn prism_api:app --host 0.0.0.0 --port $API_PORT > /tmp/api.log 2>&1 &
        echo "[$(date)] API restarted, PID: $!"
        sleep 5
        # 验证
        if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$API_PORT/health 2>/dev/null | grep -q "200"; then
            echo "[$(date)] API healthy after restart"
        else
            echo "[$(date)] API still unhealthy after restart!"
        fi
    fi
    
    # 检查cloudflare隧道是否存活
    if ! pgrep -f "cloudflared tunnel" > /dev/null 2>&1; then
        echo "[$(date)] Tunnel down, restarting..."
        nohup cloudflared tunnel --url http://localhost:$API_PORT > /tmp/tunnel.log 2>&1 &
        echo "[$(date)] Tunnel restarted, PID: $!"
        sleep 10
    fi
    
    sleep $CHECK_INTERVAL
done
