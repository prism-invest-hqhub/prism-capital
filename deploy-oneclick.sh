#!/bin/bash
# ============================================================
# 棱镜一键部署脚本 v1.0
# 用法: bash deploy-oneclick.sh
# 需要: Ubuntu 20.04+, 1核1G+内存
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔷 棱镜 Prism Capital 一键部署${NC}"
echo "================================"

# 1. 检查系统
echo -e "${YELLOW}[1/7] 检查系统环境...${NC}"
if [ ! -f /etc/lsb-release ] && [ ! -f /etc/os-release ]; then
    echo -e "${RED}仅支持Linux系统${NC}"
    exit 1
fi
echo "  OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "  CPU: $(nproc) 核"
echo "  RAM: $(free -h | awk '/^Mem:/{print $2}')"

# 2. 安装依赖
echo -e "${YELLOW}[2/7] 安装依赖...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip git curl > /dev/null 2>&1

# 3. 克隆代码
echo -e "${YELLOW}[3/7] 克隆棱镜代码...${NC}"
INSTALL_DIR="/opt/prism-capital"
if [ -d "$INSTALL_DIR" ]; then
    cd $INSTALL_DIR && git pull
else
    git clone https://github.com/prism-invest-hqhub/prism-capital.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 4. 安装Python依赖
echo -e "${YELLOW}[4/7] 安装Python依赖...${NC}"
pip3 install -q fastapi uvicorn requests pyjwt python-dotenv

# 5. 配置环境变量
echo -e "${YELLOW}[5/7] 配置环境变量...${NC}"
cd $INSTALL_DIR/prism-api

if [ ! -f .env ]; then
    echo ""
    echo -e "${YELLOW}请输入API Key（没有可直接回车跳过，后续再配）:${NC}"
    read -p "  DeepSeek API Key: " DEEPSEEK_KEY
    read -p "  Moonshot API Key: " MOONSHOT_KEY
    
    cat > .env << ENVEOF
DEEPSEEK_API_KEY=${DEEPSEEK_KEY:-NOT_SET}
MOONSHOT_API_KEY=${MOONSHOT_KEY:-NOT_SET}
ENVEOF
    echo "  .env 已创建"
else
    echo "  .env 已存在，跳过"
fi

# 6. 生成Admin Token
echo -e "${YELLOW}[6/7] 生成Admin Token...${NC}"
ADMIN_TOKEN=$(python3 -c "
import jwt, time
token = jwt.encode({
    'sub': 'owner',
    'role': 'admin',
    'scope': 'read write admin',
    'tier': 'owner',
    'rate_limit': -1,
    'iat': int(time.time()),
    'exp': int(time.time()) + 365*100*86400  # 100年
}, 'prism-capital-secret-key-2026', algorithm='HS256')
print(token)
")
echo "  Admin Token: ${ADMIN_TOKEN:0:20}...${ADMIN_TOKEN: -10}"
echo "  ⚠️ 请保存此Token，用于API认证！"

# 7. 启动API + 守护
echo -e "${YELLOW}[7/7] 启动棱镜...${NC}"

# 杀旧进程
lsof -ti :8900 2>/dev/null | xargs kill -9 2>/dev/null || true

# 启动API
source .env
export DEEPSEEK_API_KEY MOONSHOT_API_KEY
nohup python3 -m uvicorn prism_api:app --host 0.0.0.0 --port 8900 > /tmp/prism-api.log 2>&1 &
API_PID=$!
echo "  API PID: $API_PID"

# 等待启动
sleep 4

# 验证
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8900/health | grep -q "200"; then
    echo -e "  ${GREEN}API 启动成功！${NC}"
else
    echo -e "  ${RED}API 启动失败，查看日志: tail -50 /tmp/prism-api.log${NC}"
    exit 1
fi

# 安装cloudflared（如果没装）
if ! command -v cloudflared &> /dev/null; then
    echo -e "${YELLOW}  安装cloudflared隧道...${NC}"
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflared.list > /dev/null
    apt-get update -qq && apt-get install -y -qq cloudflared > /dev/null 2>&1
fi

# 启动隧道
nohup cloudflared tunnel --url http://localhost:8900 > /tmp/prism-tunnel.log 2>&1 &
TUNNEL_PID=$!
echo "  Tunnel PID: $TUNNEL_PID"
sleep 5
TUNNEL_URL=$(grep -o 'https://[a-z-]*\.trycloudflare\.com' /tmp/prism-tunnel.log | head -1)
echo "  Tunnel URL: ${TUNNEL_URL:-等待分配...}"

# 写守护脚本
cat > /opt/prism-guard.sh << 'GUARD'
#!/bin/bash
API_DIR="/opt/prism-capital/prism-api"
while true; do
    if ! curl -s -o /dev/null http://127.0.0.1:8900/health 2>/dev/null | grep -q "ok"; then
        lsof -ti :8900 | xargs kill -9 2>/dev/null
        sleep 2
        cd $API_DIR && source .env && export DEEPSEEK_API_KEY MOONSHOT_API_KEY && \
            nohup python3 -m uvicorn prism_api:app --host 0.0.0.0 --port 8900 > /tmp/prism-api.log 2>&1 &
    fi
    if ! pgrep -f "cloudflared tunnel" > /dev/null; then
        nohup cloudflared tunnel --url http://localhost:8900 > /tmp/prism-tunnel.log 2>&1 &
    fi
    sleep 60
done
GUARD
chmod +x /opt/prism-guard.sh
nohup bash /opt/prism-guard.sh > /tmp/prism-guard.log 2>&1 &
echo "  Guard PID: $!"

# 完成报告
echo ""
echo "================================"
echo -e "${GREEN}🔷 棱镜部署完成！${NC}"
echo ""
echo "  API地址: http://$(hostname -I | awk '{print $1}'):8900"
echo "  外部地址: ${TUNNEL_URL:-查看 /tmp/prism-tunnel.log}"
echo "  PWA入口: ${TUNNEL_URL:-http://localhost:8900}/app"
echo "  Admin Token: ${ADMIN_TOKEN}"
echo ""
echo "  日志位置:"
echo "    API: /tmp/prism-api.log"
echo "    Tunnel: /tmp/prism-tunnel.log"
echo "    Guard: /tmp/prism-guard.log"
echo ""
echo "  守护进程已启动，API和隧道挂掉会自动重启"
echo "================================"
