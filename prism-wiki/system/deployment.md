# 部署指南

一键部署棱镜全栈——Docker + docker-compose + 自动守护。

---

## 快速部署

```bash
# 1. 克隆代码
git clone https://github.com/prism-invest-hqhub/prism-capital.git
cd prism-capital

# 2. 一键启动
chmod +x deploy.sh
./deploy.sh

# 3. 验证
curl http://localhost:8900/health
```

## Docker部署

```bash
# 构建镜像
docker-compose build

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

## VPS迁移方案

| 方案 | 配置 | 月费 | 说明 |
|------|------|------|------|
| 入门VPS | 1核2G | ¥50-70 | 够跑API+wiki |
| 推荐VPS | 2核4G | ¥70-110 | 流畅运行+余量 |
| 甲骨文免费 | 4核ARM/24G | ¥0 | 需抢注册，最佳性价比 |

### VPS部署步骤

1. 购买VPS，SSH登录
2. 安装Docker: `curl -fsSL https://get.docker.com | sh`
3. 克隆代码: `git clone https://github.com/prism-invest-hqhub/prism-capital.git`
4. 启动服务: `cd prism-capital && ./deploy.sh`
5. 配置域名和SSL（可选）

## GitHub Pages部署（知识库）

知识库支持静态部署到GitHub Pages：

1. 生成静态HTML
2. 推送到`gh-pages`分支
3. 在GitHub仓库设置中启用Pages

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| PRISM_JWT_SECRET | prism-capital-2026-... | JWT签名密钥 |
| PRISM_ADMIN_KEY | prism-admin-2026 | Token签发管理密钥 |
| PRISM_PORT | 8900 | API端口 |

## 进程守护

prism-guard.sh 每60秒检查：
- uvicorn API进程
- cloudflared隧道进程
- 异常自动重启

---

> 代码在GitHub，随时可一键部署到任何VPS。不依赖任何平台。
