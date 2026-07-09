<div align="center">

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/managed%20by-uv-blueviolet.svg)](https://docs.astral.sh/uv/)
[![Tencent Cloud ADP](https://img.shields.io/badge/Tencent%20Cloud-ADP-006EFF)](https://www.tencentcloud.com/products/adp)
[![Feishu](https://img.shields.io/badge/Channel-Feishu-3370FF?logo=laravel&logoColor=white)](https://open.feishu.cn)
[![Docker Image](https://img.shields.io/badge/ghcr.io-adp--feishu--bridge-2496ED?logo=docker&logoColor=white)](https://ghcr.io/deadmau5v/adp-feishu-bridge)
[![CI](https://img.shields.io/badge/CI-passing-brightgreen?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)

# ADP-Feishu Bridge

**把 [腾讯云 ADP 智能体](https://www.tencentcloud.com/products/adp) 接入 [飞书](https://open.feishu.cn) 的轻量级 Bridge**

[English](README.md) • [快速开始](#-quick-start) • [部署文档](docs/DEPLOYMENT.md) • [Docker Hub](https://ghcr.io/deadmau5v/adp-feishu-bridge) • [问题反馈](https://github.com/deadmau5v/adp-feishu-bridge/issues)

</div>

---

## 📖 About

**ADP-Feishu Bridge** 是一个用 FastAPI + `lark-oapi` SDK 实现的轻量级 Bridge 服务，把腾讯云 ADP 智能体的对话能力接入到飞书机器人。

通过飞书官方提供的 **WebSocket 长连接** 接收事件（`im.message.receive_v1`），**无需公网 IP / 域名 / HTTPS 证书**，本地一键跑起来。

主要场景：
- 🤖 **飞书群 / 私聊机器人** — 接入自有 ADP 智能体，自动回复
- 🏢 **多群多用户隔离** — 按 chat_id / open_id 隔离 ADP 访客上下文
- 📜 **多轮对话** — 自动维护最近 N 轮历史，注入到 LLM 上下文
- 🚀 **零运维负担** — SDK 内部自动断线重连 / 心跳；不需要单独跑 NapCat 这种客户端

> 📝 **Note**: 这是从 [adp-napcat-bridge](https://github.com/deadmau5v/adp-napcat-bridge) 改造而来，把上游渠道从 NapCatQQ 替换为飞书。核心 ADP 调用、user_query 拼装、多轮历史等逻辑完全保留。

#### ✨ 特性

- ✅ **飞书官方 SDK 长连接** — `lark-oapi` 出站 WebSocket，自动重连 / 心跳
- ✅ **私聊 / 群聊全支持** — `chat_type=p2p/group` 自适应
- ✅ **多访客 ID 隔离** — 群聊 `group_<chat_id>`、私聊 `feishu_<open_id>`
- ✅ **结构化 user_query** — `[System] / [Context] / [History] / [Current]` 分段注入
- ✅ **多轮上下文** — 内存维护最近 N 轮（默认 6 轮，可配）
- ✅ **白名单 + 触发模式** — 群 `@机器人` 触发 / 私聊 always 触发
- ✅ **流式 / 非流式可切** — 默认攒齐再发，也可开流式分段
- ✅ **零外部存储** — 历史只存内存，重启即清
- ✅ **System Prompt 可配置** — `.env` 多行规则直接生效

#### 📑 目录

- [About](#-about)
- [Quick Start](#-quick-start)
- [Docker 部署](#-docker-部署)
- [飞书应用配置](#-飞书应用配置)
- [配置项说明](#-配置项说明)
- [user_query 拼装规则](#-user_query-拼装规则)
- [ADP v2 协议要点](#-adp-v2-协议要点)
- [常见问题](#-常见问题)
- [本地开发](#-本地开发)
- [License](#-license)

---

## 🚀 Quick Start

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) （推荐）或 pip
- 已发布的 [腾讯云 ADP 应用](https://adp.tencentcloud.com/) 及其 `AppKey`
- 已创建的 [飞书自建应用](https://open.feishu.cn/app) 及其 `App ID` / `App Secret`

### 安装

```bash
git clone https://github.com/deadmau5v/adp-feishu-bridge.git
cd adp-feishu-bridge

# 用 uv（推荐）
uv venv --python 3.12 .venv
uv pip install -r requirements.txt

# 或用 pip
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入 ADP_BOT_APP_KEY / FEISHU_APP_ID / FEISHU_APP_SECRET
```

至少需要：

```bash
# ADP 控制台 → 应用 → 发布管理 → 调用信息 → API 管理 中获取
ADP_BOT_APP_KEY=your_app_key_here

# 飞书开放平台 → 我的应用 → 应用凭证
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 启动

```bash
.venv/bin/python main.py
```

启动成功后会看到：

```
============================================================
ADP-Feishu Bridge 启动中...
  App ID:        cli_xxx***
  Domain:        feishu
  Bot open_id:   ou_xxxxxxxxxxxxxxxx
  ADP Chat URL:  https://wss.lke.cloud.tencent.com/adp/v2/chat
  ADP AppKey:    xxxx****xxxx
  触发模式:      at
  流式发送:      False
  白名单群:      全部
  白名单用户:    全部
============================================================
飞书长连接启动中 | app_id=cli_xxx*** | domain=feishu
Bridge 服务就绪，等待飞书消息...
INFO:     Uvicorn running on http://0.0.0.0:8080
```

---

## 🐳 Docker 部署

> 完整文档见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。这里给最短路径。

### docker run

```bash
docker run -d --name adp-feishu-bridge --restart unless-stopped \
  -p 8080:8080 \
  --env-file .env \
  ghcr.io/deadmau5v/adp-feishu-bridge:latest
```

### docker compose

```bash
git clone https://github.com/deadmau5v/adp-feishu-bridge.git
cd adp-feishu-bridge
cp .env.example .env && vi .env       # 填 FEISHU_APP_ID / FEISHU_APP_SECRET / ADP_BOT_APP_KEY
docker compose up -d
```

### 镜像 tag

| tag | 说明 |
|-----|------|
| `latest` | main 分支最新 |
| `1.0.0` / `1.0` / `1` | 发布的语义化版本号 |
| `sha-abc1234` | 任意 commit |

平台：**linux/amd64** + **linux/arm64**，单 manifest 自动选。

> 📝 **Note**: 飞书渠道是出站长连接，**容器不需要暴露任何入站端口**；`8080` 端口只用于健康检查。

---

## 🛠 飞书应用配置

飞书侧一共需要做四步：

### 1. 创建企业自建应用

打开 [飞书开放平台](https://open.feishu.cn/app) → **创建企业自建应用** → 填写名称、描述、图标。

### 2. 开启机器人能力

进入应用 → **机器人** → 开启「机器人能力」。

### 3. 配置事件订阅

进入应用 → **事件订阅**：

- **订阅方式**：选「**使用长连接接收事件**」（重要，否则本项目不工作）
- **添加事件**：搜索 `im.message.receive_v1`（接收消息 v2.0）→ 添加

### 4. 配置权限

进入应用 → **权限管理**，搜索并开通以下权限：

| 权限 | 用途 |
|------|------|
| `im:message` | 接收与发送消息 |
| `im:message.group_at_msg` | 接收群聊 @机器人 消息 |
| `im:message.p2p_msg` | 接收私聊消息 |
| `im:message:send_as_bot` | 以机器人身份发送消息 |

### 5. 创建版本并发布

进入应用 → **版本管理与发布** → 创建版本 → 申请发布。**企业自建应用需要企业管理员审批**，联系管理员通过后，机器人才会在群里真正可用。

### 6. 获取 Bot open_id（强烈建议）

启动 bridge 之前，**先获取机器人自己的 open_id** 并填到 `.env` 的 `FEISHU_BOT_OPEN_ID`，否则群聊里无法准确识别"@机器人"。

获取方式：

```bash
# 用 curl 调飞书 API（替换成自己的 App ID / Secret）
curl -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal \
  -H "Content-Type: application/json" \
  -d '{"app_id":"cli_xxx","app_secret":"xxx"}'
# 拿到 tenant_access_token 后：
curl https://open.feishu.cn/open-apis/bot/v3/info \
  -H "Authorization: Bearer <tenant_access_token>"
# 响应里 bot.open_id 即为机器人 open_id
```

或者用本项目辅助脚本（见 `scripts/get_bot_open_id.py`，暂未提供，可手动 curl）。

### 7. 在群里添加机器人

打开飞书群 → 群设置 → 群机器人 → 添加机器人 → 搜索你的应用名 → 添加。
**只有添加了机器人的群，群消息才会推送到本服务**（飞书权限模型）。

---

## 🔧 配置项说明

完整列表见 [`.env.example`](.env.example)。下面挑重要的：

### ADP 配置

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `ADP_BOT_APP_KEY` | *必填* | ADP 控制台 → 应用 → 发布管理 → 调用信息 → API 管理 |
| `ADP_CHAT_URL` | `https://wss.lke.cloud.tencent.com/adp/v2/chat` | v2 接口地址，一般不用改 |
| `ADP_VISITOR_ID` | `feishu-bridge` | 默认访客 ID（运行时会被覆盖，详见下文） |

### 飞书配置

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `FEISHU_APP_ID` | *必填* | 飞书应用 App ID（`cli_` 开头） |
| `FEISHU_APP_SECRET` | *必填* | 飞书应用 App Secret |
| `FEISHU_DOMAIN` | `feishu` | `feishu`（国内）/ `lark`（海外） |
| `FEISHU_BOT_OPEN_ID` | 空 | 机器人 open_id（强烈建议填，群聊 @识别 用） |
| `FEISHU_LOG_LEVEL` | `INFO` | 飞书 SDK 日志级别 |

### Bridge 行为

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `BRIDGE_TRIGGER_MODE` | `at` | `at`（群 @机器人 触发 / 私聊 always）/ `always`（所有消息触发） |
| `BRIDGE_ALLOWED_CHATS` | 空 | chat_id 白名单（逗号分隔），空=不过滤 |
| `BRIDGE_ALLOWED_USERS` | 空 | open_id 白名单（逗号分隔），空=不过滤 |
| `BRIDGE_MAX_HISTORY_TURNS` | `6` | 拼到 user_query 的最近历史轮数；`0`=不传历史 |
| `BRIDGE_MAX_QUERY_LENGTH` | `3000` | user_query 字符上限（超长按 FIFO 丢历史） |
| `BRIDGE_STREAMING_SEND` | `false` | `true`=按 ADP 片段分段发；`false`=攒齐再发 |
| `BRIDGE_STREAMING_BATCH_SIZE` | `50` | 流式模式下每批字符数 |
| `BRIDGE_MAX_MSG_LENGTH` | `4000` | 单条飞书消息最大长度（超长自动分段发） |

### 系统提示词

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `BRIDGE_SYSTEM_PROMPTS` | 禁用 Markdown 模板 | 拼到每次请求头部 `[System]` 段；多行用 `\n` |

---

## 🧠 user_query 拼装规则

每次请求，handler 把上游消息拼成如下结构，作为单条 `user_query` 发给 ADP：

```
[System]
你正在通过飞书聊天机器人回复用户。
请使用纯文本回复：不要用 # 标题、**粗体**、*斜体*、代码块、列表符号、链接语法等任何 Markdown 标记。
...
[Context] type=group | from=张三(ou_xxx) | chat=oc_xxxx | session=group_oc_xxxx
[History]
[user] 张三: 之前问的那个问题再说一下
[assistant] 丁真: ...
[user] 李四: 我也想了解
[Current] @丁真 帮我看看这两个
```

字段含义：

- **`[System]`** — 全局规则，每次都带（来自 `BRIDGE_SYSTEM_PROMPTS`）
- **`[Context]`** — 上游消息元数据，让 LLM 知道是群/私聊、谁发的、哪个 session
- **`[History]`** — 最近 N 轮对话（`BRIDGE_MAX_HISTORY_TURNS` 控制）
- **`[Current]`** — 本轮真实消息（已剥离 `@_user_x` 飞书占位符）

> ⚠️ **Note**: 当总长超过 `BRIDGE_MAX_QUERY_LENGTH` 时，**`[System] / [Context] / [Current]` 永远保留**，从 `[History]` 头部按行丢到合适为止。

---

## 📡 ADP v2 协议要点

| 字段 | 规则 |
|------|------|
| `ConversationId` | UUID，校验 `^[a-zA-Z0-9_-]{32,64}$`，**每次必须用新值或固定 session 串上下文** |
| `VisitorId` | 字符串，标识访客（影响上下文关联、用量统计、平台端用户权限） |
| `Contents` | `[{ "Type": "text", "Text": "..." }]`，可扩展 image / file / custom_variables |
| `Stream` | `"enable"` / `"disable"` |
| `Incremental` | `true` 时 ADP 可能返回 `text.replace` 事件（增量模式下偶尔出现） |

### VisitorId 策略

| 场景 | 访客 ID | 行为 |
|------|---------|------|
| 群聊 | `group_<chat_id>` | 整群共享上下文，多用户聊也串得起 |
| 私聊 | `feishu_<open_id>` | 每用户独立上下文 |

> 📝 **Note**: ADP v1 接口 `https://wss.lke.cloud.tencent.com/v1/qbot/chat/sse` 已废弃，会返回 `460030 该应用类型不支持当前请求`。**本项目只支持 v2。**

### ADP SSE 事件流

| 事件 | 含义 | 处理 |
|------|------|------|
| `request_ack` / `response.created` / `message.added` / `content.added` | 控制流 | 忽略 |
| `text.delta` | 文本增量 | 累积到 buffer |
| `text.replace` | 文本替换（增量模式下偶尔出现） | 重置 buffer |
| `message.done` (Type=`reply`) | **消息完成** | **提取最终完整回复发出** |
| `response.completed` | 响应完成 | 标记流结束 |
| `error` | 错误 | 把 `Error.Message` 作为回复发回用户 |

---

## ❓ 常见问题

<details>
<summary><b>Q: 启动后日志说"飞书长连接启动中"但收不到消息？</b></summary>

A: 检查四件事：
1. 飞书后台「事件订阅」是否选的是「**使用长连接接收事件**」（不是 webhook）
2. 权限是否包含 `im:message.group_at_msg`（群聊） / `im:message.p2p_msg`（私聊）
3. 应用是否已**发布并通过审批**（企业自建应用需要管理员批准）
4. 群设置里是否已**添加该机器人**（未添加的群，飞书不会推送事件）
</details>

<details>
<summary><b>Q: 群里 @ 机器人但没反应？</b></summary>

A: 检查 `FEISHU_BOT_OPEN_ID` 是否正确填写。这是群聊里识别"@机器人"的关键配置。
</details>

<details>
<summary><b>Q: 怎么让机器人不响应某个群？</b></summary>

A: 把该群的 `chat_id` 排除。`chat_id` 在日志 `处理消息 | ... | chat=oc_xxx` 里能看到。
如果不填 `BRIDGE_ALLOWED_CHATS`，默认全过（飞书侧已限制只有添加机器人的群才会推事件）。
</details>

<details>
<summary><b>Q: 历史会持久化吗？</b></summary>

A: 不持久化，重启即清。多轮对话靠每次请求拼接历史实现，不是 ADP 端的 server-side 状态。
</details>

<details>
<summary><b>Q: 报错 <code>ADP {code} 消息</code>？</b></summary>

A: 看 [腾讯云 ADP 错误码](https://cloud.tencent.com/document/product/1759/129202#4-错误码)。常见：
- `460030` 应用类型不支持当前请求 → 用了 v1 接口，改 v2
- `460919` 会话 ID 已存在 → 用了文档示例的固定 UUID，必须用新生成的
</details>

<details>
<summary><b>Q: ADP 回复里夹带 Markdown 怎么办？</b></summary>

A: 默认 `BRIDGE_SYSTEM_PROMPTS` 已经包含"严禁 Markdown"规则。飞书客户端不渲染 Markdown，看到 `#`/`**` 之类会原样显示。如果你用了自己的 System Prompt 但忘了加这条规则，回复就会出 Markdown 符号。
</details>

---

## 👨‍💻 本地开发

```bash
# 装 dev 依赖
uv pip install -r requirements.txt
# 改完代码后重启
pkill -f "python main.py" 2>&1
.venv/bin/python main.py

# 看 log
# 直接看 stdout；如果用 tmux：tmux capture-pane -p -S -100
```

### 目录结构

```
adp-feishu-bridge/
├── main.py             # FastAPI 入口 + 飞书长连接生命周期管理
├── adp_client.py       # ADP v2 SSE 客户端（不变）
├── feishu_client.py    # 飞书 SDK 长连接 + REST 发消息
├── handler.py          # 消息处理：白名单/触发/历史/user_query 拼装
├── config.py           # .env 配置加载
├── constants.py        # 项目级常量
├── requirements.txt    # 依赖
├── Dockerfile          # 多阶段构建（uv 安装 → slim 运行）
├── docker-compose.yml  # bridge 容器编排
├── .dockerignore
├── .github/workflows/
│   ├── ci.yml          # ruff + mypy + smoke import
│   └── docker-publish.yml  # tag v*.*.* 触发多架构镜像发布
├── docs/
│   └── DEPLOYMENT.md   # 完整部署文档
├── .env.example        # 配置模板
├── .env                # 实际配置（含 AppKey，gitignore）
├── .gitignore
├── LICENSE             # MIT
└── README.md
```

### 日志 Logger 命名

所有 logger 都通过 `constants.APP_NAME` 生成：

```
adp-feishu-bridge.main      # 启动 / 路由
adp-feishu-bridge.adp       # ADP HTTP 调用
adp-feishu-bridge.feishu    # 飞书长连接 / REST
adp-feishu-bridge.handler   # 消息处理
```

调试时改 `BRIDGE_DEBUG_RAW_EVENT=true` 可打印原始飞书事件。

---

## 📜 License

[MIT](LICENSE) © 2026 adp-feishu-bridge contributors
