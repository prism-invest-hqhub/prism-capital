#!/bin/bash
set -e

echo "🔷 棱镜 Prism Capital — 一键部署"
echo "=================================="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "📦 安装 Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
fi

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "📦 安装 Docker Compose..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Build and start
echo "🔨 构建棱镜镜像..."
docker-compose build

echo "🚀 启动棱镜服务..."
docker-compose up -d

echo ""
echo "⏳ 等待服务启动..."
sleep 5

# Health check
if curl -s http://localhost:8900/health | grep -q "alive"; then
    echo "✅ 棱镜已上线！"
    echo ""
    echo "📍 本地地址: http://localhost:8900"
    echo "📱 PWA界面: http://localhost:8900/app"
    echo "🔑 签发Token: curl -X POST http://localhost:8900/token -H 'Content-Type: application/json' -d '{\"admin_key\":\"prism-admin-2026\",\"subject\":\"your-name\",\"role\":\"admin\",\"expiry_days\":36500}'"
else
    echo "❌ 启动失败，检查日志: docker-compose logs"
fi
