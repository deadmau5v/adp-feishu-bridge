# 部署指南

> 将 **ADP-Feishu Bridge** 部署到生产环境的完整步骤。
> 涵盖 Docker / docker-compose / `uv` 直跑 三种方式。
>
> **相对 NapCat 版本的差异**：飞书渠道通过出站长连接直连飞书，**不需要 NapCat 容器**，部署更简单。

---

## 目录

- [1. 前置准备](#1-前置准备)
  - [1.1 申请腾讯云 ADP 应用](#11-申请腾讯云-adp-应用)
  - [1.2 创建飞书自建应用](#12-创建飞书自建应用)
- [2. 方式 A：Docker Run（最快）](#2-方式-adocker-run最快)
- [3. 方式 B：docker-compose（推荐）](#3-方式-bdocker-compose推荐)
- [4. 方式 C：本地 `uv` 部署（无 Docker）](#4-方式-本地-uv-部署无-docker)
- [5. 启动后的配置](#5-启动后的配置)
  - [5.1 获取 Bot open_id](#51-获取-bot-open_id)
  - [5.2 在群里添加机器人](#52-在群里添加机器人)
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

### 1.2 创建飞书自建应用

完整步骤见 [README.md - 飞书应用配置](../README.md#-飞书应用配置)。简要清单：

| 步骤 | 关键点 |
|------|--------|
| 1. 创建企业自建应用 | [飞书开放平台](https://open.feishu.cn/app) |
| 2. 开启机器人能力 | 应用 → 机器人 |
| 3. 事件订阅方式 | **使用长连接接收事件**（不是 webhook） |
| 4. 订阅事件 | `im.message.receive_v1` |
| 5. 权限 | `im:message`, `im:message.group_at_msg`, `im:message.p2p_msg`, `im:message:send_as_bot` |
| 6. 创建版本并发布 | 企业自建应用需管理员审批 |
| 7. 拿到 App ID / App Secret | 应用 → 凭证与基础信息 |

> ⚠️ **注意**：在「事件订阅」页面必须选「使用长连接接收事件」而不是「将事件发送至开发者服务器」，否则本项目不工作。

---

## 2. 方式 A：Docker Run（最快）

适合只需要跑 bridge 一台机的场景。

```bash
# 1. 拉取最新镜像
docker pull ghcr.io/deadmau5v/adp-feishu-bridge:latest

# 2. 准备配置目录
mkdir -p /opt/adp-feishu-bridge && cd /opt/adp-feishu-bridge
curl -fsSL https://raw.githubusercontent.com/deadmau5v/adp-feishu-bridge/main/.env.example -o .env
vi .env   # 填入 ADP_BOT_APP_KEY / FEISHU_APP_ID / FEISHU_APP_SECRET

# 3. 启动
docker run -d \
  --name adp-feishu-bridge \
  --restart unless-stopped \
  -p 8080:8080 \
  --env-file /opt/adp-feishu-bridge/.env \
  ghcr.io/deadmau5v/adp-feishu-bridge:latest

# 4. 看日志
docker logs -f adp-feishu-bridge
```

| 优势 | 劣势 |
|------|------|
| 3 行命令上线 | 升级 = 重拉镜像 |
| 飞书是出站连接，不依赖端口映射 | 不带自愈（要靠 `--restart`） |

> 📝 **Note**: 容器只需要暴露 `8080` 端口用于健康检查；飞书长连接是出站到 `open.feishu.cn`，**不需要也不应该**用反向代理 / 域名 / 证书。

---

## 3. 方式 B：docker-compose（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/deadmau5v/adp-feishu-bridge.git
cd adp-feishu-bridge

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
ADP_BOT_APP_KEY=<你的单 Agent AppKey>

# ── 飞书 ──
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# 强烈建议：填机器人的 open_id（先启动一次用 curl 取，见 5.1）
FEISHU_BOT_OPEN_ID=

# ── 触发生效范围 ──
BRIDGE_ALLOWED_CHATS=oc_xxx1,oc_xxx2
BRIDGE_ALLOWED_USERS=ou_xxx1
```

### 3.2 升级

```bash
docker compose pull
docker compose up -d
```

---

## 4. 方式 C：本地 `uv` 部署（无 Docker）

适合 TencentOS 3.2 这类**没有 Docker 也没有 systemd** 的环境。

```bash
# 0. 安装 uv（如未装）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

# 1. 克隆 & 准备 venv
git clone https://github.com/deadmau5v/adp-feishu-bridge.git
cd adp-feishu-bridge
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
tmux new-session -d -s adp-feishu-bridge -x 200 -y 50 \
  'cd /data/adp-feishu-bridge && .venv/bin/python main.py; exec bash'

# 重新连上
tmux attach -t adp-feishu-bridge
```

### 4.2 开机自启（crond 方案）

```bash
# 写启动脚本
cat > /opt/adp-feishu-bridge/restart.sh <<'EOF'
#!/bin/bash
tmux kill-session -t adp-feishu-bridge 2>/dev/null
cd /data/adp-feishu-bridge
tmux new-session -d -s adp-feishu-bridge -x 200 -y 50 '.venv/bin/python main.py; exec bash'
EOF
chmod +x /opt/adp-feishu-bridge/restart.sh

# crond 每 5 分钟检查一次（bridge 挂了自动拉起）
crontab -e
# 加一行：
*/5 * * * * /opt/adp-feishu-bridge/restart.sh >> /var/log/adp-feishu-bridge.log 2>&1
```

> **注意**：容器环境下 PID 1 是 `run` 而非 systemd，crond 需手工 `crond` 启动。

---

## 5. 启动后的配置

### 5.1 获取 Bot open_id

启动后第一次不知道 `FEISHU_BOT_OPEN_ID` 也没关系，可以从飞书 API 拉：

```bash
# 1) 拿 tenant_access_token
TOKEN=$(curl -s -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal \
  -H "Content-Type: application/json" \
  -d "{\"app_id\":\"$FEISHU_APP_ID\",\"app_secret\":\"$FEISHU_APP_SECRET\"}" \
  | python -c "import json,sys; print(json.load(sys.stdin)['tenant_access_token'])")

# 2) 查机器人 open_id
curl -s https://open.feishu.cn/open-apis/bot/v3/info \
  -H "Authorization: Bearer $TOKEN"
```

响应里 `bot.open_id` 即为机器人自己的 open_id，填到 `.env` 的 `FEISHU_BOT_OPEN_ID`，重启 bridge 即可。

### 5.2 在群里添加机器人

飞书的权限模型是「**只有添加了机器人的群，群消息才会被推送到应用**」：

1. 打开飞书群 → 群设置 → 群机器人
2. 添加机器人 → 搜索你的应用名 → 添加

> 📝 **Note**: 添加机器人后，群里的 @机器人 消息才会触发本服务；私聊则只要用户跟机器人对话就会触发。

---

## 6. 验证

```bash
# 1. bridge 健康检查
curl http://127.0.0.1:8080/health
# {"status":"ok","service":"adp-feishu-bridge"}

# 2. 看启动 banner
docker logs adp-feishu-bridge | head -30
# 应该看到：
#   ✓ ADP-Feishu Bridge 启动中...
#   ✓ 飞书长连接启动中
#   ✓ Bridge 服务就绪，等待飞书消息...

# 3. 在飞书群里 @机器人 发消息
#    应该看到 ADP 智能体的回复
```

如果没回复，依次查：

| 排查点 | 位置 |
|--------|------|
| 飞书长连接是否起来 | 日志 `飞书长连接启动中` |
| 事件订阅方式 | 飞书后台 → 事件订阅 → 「使用长连接接收事件」 |
| 应用是否已发布 | 飞书后台 → 版本管理与发布 |
| 群是否已添加机器人 | 群设置 → 群机器人 |
| 触发条件 | `BRIDGE_TRIGGER_MODE=at` 时必须 @ 机器人 |
| 群聊 @识别 | `FEISHU_BOT_OPEN_ID` 是否正确 |
| 白名单 | 你的 `open_id`/`chat_id` 是否在 `BRIDGE_ALLOWED_*` 里 |
| ADP v2 是否返回 | 看日志的 SSE event 列表 |

---

## 7. 升级与回滚

### Docker 部署

```bash
# 升级
docker compose pull && docker compose up -d

# 回滚
docker tag ghcr.io/deadmau5v/adp-feishu-bridge:1.0.0 adp-feishu-bridge:stable
docker compose down
docker run -d --name adp-feishu-bridge ... adp-feishu-bridge:stable
```

### uv 部署

```bash
cd /data/adp-feishu-bridge
git pull
uv pip install -r requirements.txt
tmux kill-session -t adp-feishu-bridge
tmux new-session -d -s adp-feishu-bridge -x 200 -y 50 '.venv/bin/python main.py; exec bash'
```

---

## 8. 常见问题

<details>
<summary><b>Q：启动报 "FEISHU_APP_ID 未配置" / "FEISHU_APP_SECRET 未配置"</b></summary>

.env 没填这两个变量，或者 `.env` 不在启动目录。检查：
```bash
# 1) 文件存在
ls -la .env
# 2) 字段存在且非空
grep -E "^(FEISHU_APP_ID|FEISHU_APP_SECRET)=" .env
# 3) 进程的工作目录
pwd
```
</details>

<details>
<summary><b>Q：飞书长连接起来了但收不到消息</b></summary>

按顺序排查：
1. **订阅方式**：飞书后台「事件订阅」必须是「**使用长连接接收事件**」，不是 webhook
2. **权限范围**：群消息需要 `im:message.group_at_msg`；私聊需要 `im:message.p2p_msg`
3. **应用状态**：必须已发布且通过企业管理员审批
4. **群权限**：必须在群里手动添加机器人（飞书默认不主动加）
5. **触发模式**：`BRIDGE_TRIGGER_MODE=at` 时必须 @ 机器人，且 `FEISHU_BOT_OPEN_ID` 已正确填写

调试时打开 `BRIDGE_DEBUG_RAW_EVENT=true`，看是否真的收到了飞书事件。
</details>

<details>
<summary><b>Q：日志里处理了消息但没有回复</b></summary>

通常是 ADP 端报错。看 `error` event 的 payload：

| code | 含义 |
|------|------|
| 460030 | 用错了 v1 接口（必须用 v2） |
| 460919 | VisitorId 重复，改成动态 `group_<chat_id>` / `feishu_<open_id>` |
| 401/403 | AppKey 错或未发版本 |

打开 `BRIDGE_LOG_LEVEL=DEBUG` 看完整 SSE 事件流。
</details>

<details>
<summary><b>Q：群消息不触发但私聊正常？</b></summary>

三选一原因：
1. 群没添加机器人（飞书侧拦截）
2. 消息没 @ 机器人（`BRIDGE_TRIGGER_MODE=at` 默认行为）
3. `FEISHU_BOT_OPEN_ID` 没填 / 填错（无法识别"@机器人"）

临时测试：把 `BRIDGE_TRIGGER_MODE` 改成 `always`，看群消息会不会触发；如果触发了，确认 1+2；如果还没触发，查 1。
</details>

<details>
<summary><b>Q：arm64 机器拉镜像报 platform 错？</b></summary>

默认 latest 是多架构镜像，应该自动选 arm64。如果失败：
```bash
docker pull --platform linux/arm64 ghcr.io/deadmau5v/adp-feishu-bridge:latest
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
ghcr.io/deadmau5v/adp-feishu-bridge:latest
ghcr.io/deadmau5v/adp-feishu-bridge:1.0.0          # 发布版本
ghcr.io/deadmau5v/adp-feishu-bridge:sha-abc1234   # 任意 commit
```
