# 部署指南

> 将 **ADP-NapCatQQ Bridge** 部署到生产环境的完整步骤。
> 涵盖 Docker / docker-compose 两种主流方式，以及在无 Docker 环境下用 `uv` 直跑。

---

## 目录

- [1. 前置准备](#1-前置准备)
  - [1.1 申请腾讯云 ADP 应用](#11-申请腾讯云-adp-应用)
  - [1.2 部署 NapCatQQ](#12-部署-napcatqq)
- [2. 方式 A：Docker Run（最快）](#2-方式-adocker-run最快)
- [3. 方式 B：docker-compose（推荐）](#3-方式-bdocker-compose推荐)
- [4. 方式 C：本地 `uv` 部署（无 Docker）](#4-方式-本地-uv-部署无-docker)
- [5. 启动后的配置](#5-启动后的配置)
  - [5.1 登录 NapCat 扫码](#51-登录-napcat-扫码)
  - [5.2 配置 NapCat 反向 WebSocket](#52-配置-napcat-反向-websocket)
- [6. 验证](#6-验证)
- [7. 升级与回滚](#7-升级与回滚)
- [8. 常见问题](#8-常见问题)

---

## 1. 前置准备

### 1.1 申请腾讯云 ADP 应用

1. 登录 [腾讯云智能体开发平台 (LKE)](https://cloud.tencent.com/product/lke)
2. 在应用列表中创建一个**单 Agent** 应用，开启"工具调用" / "知识库"（按需）
3. 拿到 `AppKey`（注意是**单 Agent 应用**的 AppKey，不是智能体本身的 Bot Token）
   - 控制台 → 应用 → 调用信息 → API 调用密钥
4. 发布一个版本（每次调 ADP v2 SSE 都要传 `OnlineSearch` 标识的发布版本）

### 1.2 部署 NapCatQQ

任选其一：

| 方案 | 适合 | 文档 |
|------|------|------|
| **mlikiowa/napcat-docker** | 不想装原生、有 Docker 即可 | https://hub.docker.com/r/mlikiowa/napcat-docker |
| **NapCat AppImage** | TencentOS / 老内核 / 无 Docker | [NapCat 官方安装文档](https://napcat.doc.rie.ink/) |
| **Windows 原生** | 本地测试 | [NapCat 官方安装文档](https://napcat.doc.rie.ink/) |

> **关键配置（无论哪种方案都需设置）**：
> - onebot11 HTTP 服务：`127.0.0.1:3001`（`127.0.0.1` 即可，bridge 默认在同机/同网络可达）
> - onebot11 反向 WebSocket Client：`ws://<bridge-host>:8080/onebot/v11/ws`
> - 网络：HTTP 与反向 WS 至少开一个（推荐两个都开）

---

## 2. 方式 A：Docker Run（最快）

适合只需要跑 bridge 一台机，NapCat 已在别处运行的情况。

```bash
# 1. 拉取最新镜像
docker pull ghcr.io/deadmau5v/adp-napcat-bridge:latest

# 2. 准备配置目录
mkdir -p /opt/adp-bridge && cd /opt/adp-bridge
curl -fsSL https://raw.githubusercontent.com/deadmau5v/adp-napcat-bridge/main/.env.example -o .env
vi .env   # 填入 ADP_APP_KEY / ADP_BOT_APP_KEY / NAPCAT_HTTP_URL / BRIDGE_ALLOWED_USERS

# 3. 启动
docker run -d \
  --name adp-bridge \
  --restart unless-stopped \
  -p 8080:8080 \
  --env-file /opt/adp-bridge/.env \
  -e BRIDGE_HOST=0.0.0.0 \
  -e BRIDGE_PORT=8080 \
  ghcr.io/deadmau5v/adp-napcat-bridge:latest

# 4. 看日志
docker logs -f adp-bridge
```

| 优势 | 劣势 |
|------|------|
| 3 行命令上线 | NapCat 单独管 |
| 升级 = 重拉镜像重启 | 不带自愈（要靠 `--restart`） |

---

## 3. 方式 B：docker-compose（推荐）

适合要同时管 NapCat + bridge 的场景。

```bash
# 1. 克隆仓库
git clone https://github.com/deadmau5v/adp-napcat-bridge.git
cd adp-napcat-bridge

# 2. 准备 .env
cp .env.example .env
vi .env   # 见下方"必填项"清单

# 3. 启动
docker compose up -d

# 4. 看日志
docker compose logs -f bridge
```

### 3.1 `.env` 必填项

```ini
# ── ADP ──
ADP_APP_KEY=<你的 AppKey>
ADP_BOT_APP_KEY=<同上，单 Agent 的 AppKey>

# ── NapCat 容器内可达的 HTTP 地址 ──
# 容器内 NapCat 服务名是 napcat（同网络），不要写 127.0.0.1
NAPCAT_HTTP_URL=http://napcat:3001

# ── 触发生效范围 ──
BRIDGE_ALLOWED_USERS=你的QQ号
BRIDGE_ALLOWED_GROUPS=你的群号
```

### 3.2 升级

```bash
docker compose pull bridge
docker compose up -d
```

### 3.3 仅启 bridge（NapCat 在别处）

```bash
docker compose up -d bridge
# 并把 .env 里 NAPCAT_HTTP_URL 改成现成实例的地址
```

---

## 4. 方式 C：本地 `uv` 部署（无 Docker）

适合 TencentOS 3.2 这类**没有 Docker 也没有 systemd** 的环境。

```bash
# 0. 安装 uv（如未装）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

# 1. 克隆 & 准备 venv
git clone https://github.com/deadmau5v/adp-napcat-bridge.git
cd adp-napcat-bridge
uv venv --python 3.12 .venv
uv pip install -r requirements.txt

# 2. 配置
cp .env.example .env
vi .env

# 3. 测试启动
.venv/bin/python main.py
```

### 4.1 持久化（用 tmux 替代 systemd）

```bash
# 拉一个会话
tmux new-session -d -s adp-bridge -x 200 -y 50 \
  'cd /data/adp-bridge && .venv/bin/python main.py; exec bash'

# 重新连上
tmux attach -t adp-bridge
```

### 4.2 开机自启（crond 方案）

```bash
# 写启动脚本
cat > /opt/adp-bridge/restart.sh <<'EOF'
#!/bin/bash
tmux kill-session -t adp-bridge 2>/dev/null
cd /data/adp-bridge
tmux new-session -d -s adp-bridge -x 200 -y 50 '.venv/bin/python main.py; exec bash'
EOF
chmod +x /opt/adp-bridge/restart.sh

# crond 每 5 分钟检查一次（bridge 挂了自动拉起）
crontab -e
# 加一行：
*/5 * * * * /opt/adp-bridge/restart.sh >> /var/log/adp-bridge.log 2>&1
```

> **注意**：容器环境下 PID 1 是 `run` 而非 systemd，crond 需手工 `crond` 启动。

---

## 5. 启动后的配置

### 5.1 登录 NapCat 扫码

如果是 Docker 部署：

```bash
# 浏览器打开 WebUI
open http://<host>:6099
# 扫码登录 QQ 小号
```

如果是无头服务器 + SSH 转发：

```bash
ssh -L 6099:127.0.0.1:6099 user@server
# 本地浏览器开 http://127.0.0.1:6099
```

### 5.2 配置 NapCat 反向 WebSocket

NapCat 控制台（或直接编辑 `data/config/onebot11_<QQ>.json`）：

```json
{
  "network": {
    "httpServers": [
      { "enable": true, "host": "127.0.0.1", "port": 3001, "enableCors": true }
    ],
    "websocketServers": [],
    "websocketClients": [
      {
        "enable": true,
        "url": "ws://127.0.0.1:8080/onebot/v11/ws"
      }
    ]
  }
}
```

bridge 启动后日志应出现：

```
✓ NapCat 反向 WebSocket 已连接 | from=127.0.0.1:xxxxx
```

---

## 6. 验证

```bash
# 1. bridge 健康检查
curl http://127.0.0.1:8080/healthz
# {"status":"ok"}

# 2. NapCat 在线
curl http://127.0.0.1:3001/get_login_info
# {"retcode":0,"data":{"user_id":2020268674,"nickname":"丁真"}}

# 3. 在 QQ 给机器人发消息（@ 机器人）
#    应该看到 ADP 智能体的回复
```

如果没回复，依次查：

| 排查点 | 命令 / 位置 |
|--------|-------------|
| bridge 日志 | `docker logs -f adp-bridge` / tmux 输出 |
| NapCat 日志 | docker 同上 / `/data/napcat/logs/` |
| WS 是否连上 | bridge 启动 banner `✓ 反向 WebSocket 已连接` |
| ADP v2 是否返回 | 看 bridge 日志的 SSE event 列表 |
| 触发条件 | `BRIDGE_TRIGGER_MODE=at` 时必须 @ 机器人；`all` 不用 |
| 白名单 | 你的 QQ 号是否在 `BRIDGE_ALLOWED_USERS` 里 |

---

## 7. 升级与回滚

### Docker 部署

```bash
# 升级
docker compose pull && docker compose up -d

# 回滚
docker tag ghcr.io/deadmau5v/adp-napcat-bridge:1.0.0 adp-bridge:stable
docker compose down
docker run -d --name adp-bridge ... adp-bridge:stable
```

### uv 部署

```bash
cd /data/adp-bridge
git pull
uv pip install -r requirements.txt
tmux kill-session -t adp-bridge
tmux new-session -d -s adp-bridge -x 200 -y 50 '.venv/bin/python main.py; exec bash'
```

---

## 8. 常见问题

<details>
<summary><b>Q：bridge 启动报 "Cannot connect to NapCat"</b></summary>

先确认 NapCat 容器先起来且健康。docker-compose 中已用 `depends_on: napcat: condition: service_healthy` 等待。如果还报，检查：

```bash
docker exec adp-bridge curl http://napcat:3001/get_login_info
```

如果 `get_login_info` 返回 `not login` 之类，说明 NapCat 还没扫码。
</details>

<details>
<summary><b>Q：用户消息没触发回复</b></summary>

- 群消息默认要 @ 机器人（`BRIDGE_TRIGGER_MODE=at`）
- 检查白名单：你的 QQ 号必须在 `BRIDGE_ALLOWED_USERS` 中
- 看 bridge 日志确认收到了 message 事件
</details>

<details>
<summary><b>Q：bridge 日志大量 "处理消息时发生错误"</b></summary>

通常是 ADP 端报错。看日志里的 SSE 事件里的 `error` payload，常见有：

| code | 含义 |
|------|------|
| 460030 | 用错了 v1 接口 |
| 460919 | VisitorId 重复，改成动态 `group_<id>` / `qq_<id>` |
| 401/403 | AppKey 错或未发版本 |
</details>

<details>
<summary><b>Q：arm64 机器拉镜像报 platform 错</b></summary>

默认 latest 是多架构镜像，应该自动选 arm64。如果失败：

```bash
docker pull --platform linux/arm64 ghcr.io/deadmau5v/adp-napcat-bridge:latest
```
</details>

<details>
<summary><b>Q：怎么发版本？</b></summary>

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions 会自动：
1. 跑 CI
2. 构建多架构镜像
3. 推 `latest` / `1.0.0` / `1.0` / `1` / `sha-xxxxxxx` tag 到 GHCR
4. 创建 GitHub Release
</details>

---

## 镜像地址

```
ghcr.io/deadmau5v/adp-napcat-bridge:latest
ghcr.io/deadmau5v/adp-napcat-bridge:1.0.0   # 发布版本
ghcr.io/deadmau5v/adp-napcat-bridge:sha-abc1234  # 任意 commit
```
