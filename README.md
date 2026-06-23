<div align="center">

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/managed%20by-uv-blueviolet.svg)](https://docs.astral.sh/uv/)
[![Tencent Cloud ADP](https://img.shields.io/badge/Tencent%20Cloud-ADP-006EFF)](https://www.tencentcloud.com/products/adp)

# ADP-NapCatQQ Bridge

**把 [腾讯云 ADP 智能体](https://www.tencentcloud.com/products/adp) 接入 [NapCatQQ](https://github.com/NapNeko/NapCatQQ) 的轻量级 Bridge**

[English](README.md) • [快速开始](#-quick-start) • [问题反馈](https://github.com/deadmau5v/adp-napcat-bridge/issues)

</div>

---

## 📖 About

**ADP-NapCatQQ Bridge** 是一个用 FastAPI 实现的轻量级 Bridge 服务，把腾讯云 ADP 智能体的对话能力接入到 NapCatQQ（基于 NTQQ 的 OneBot v11 协议端），让你的 QQ 机器人可以自动回复用户消息。

主要场景：
- 🤖 **QQ 群 / 私聊机器人** — 接入自有 ADP 智能体，自动回复
- 🏢 **多群多用户隔离** — 按群号 / QQ 号隔离 ADP 访客上下文
- 📜 **多轮对话** — 自动维护最近 N 轮历史，注入到 LLM 上下文

#### ✨ 特性

- ✅ **原生支持 ADP v2 SSE** — 流式解析 `text.delta` / `message.done` / `response.completed` 等事件
- ✅ **多访客 ID 隔离** — 群聊 `group_<id>`、私聊 `qq_<id>`
- ✅ **结构化 user_query** — `[System] / [Context] / [History] / [Current]` 分段注入
- ✅ **多轮上下文** — 内存维护最近 N 轮（默认 6 轮，可配）
- ✅ **白名单 + 触发模式** — 群 `@机器人` 触发 / 私聊 always 触发
- ✅ **流式 / 非流式可切** — 默认攒齐再发，也可开流式分段
- ✅ **零外部存储** — 历史只存内存，重启即清
- ✅ **System Prompt 可配置** — `.env` 多行规则直接生效

#### 📑 目录

- [About](#-about)
- [Quick Start](#-quick-start)
- [NapCatQQ 配置](#-napcatqq-配置)
- [配置项说明](#-配置项说明)
- [user_query 拼装规则](#-user_query-拼装规则)
- [ADP v2 协议要点](#-adp-v2-协议要点)
- [部署提示](#-部署提示)
- [常见问题](#-常见问题)
- [本地开发](#-本地开发)
- [License](#-license)

---

## 🚀 Quick Start

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) （推荐）或 pip
- 已部署的 [NapCatQQ](https://github.com/NapNeko/NapCatAppImageBuild)，机器人 QQ 已扫码登录
- 腾讯云 [ADP 控制台](https://adp.tencentcloud.com/) 上已发布一个应用，并拿到 `AppKey`

### 安装

```bash
git clone https://github.com/deadmau5v/adp-napcat-bridge.git
cd adp-napcat-bridge

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
# 编辑 .env，填入 ADP_BOT_APP_KEY
```

至少需要：

```bash
# ADP 控制台 → 应用 → 发布管理 → 调用信息 → API 管理 中获取
ADP_BOT_APP_KEY=your_app_key_here
```

### 启动

```bash
.venv/bin/python main.py
```

启动成功后会看到：

```
============================================================
ADP-NapCatQQ Bridge 启动中...
  连接模式:     reverse_ws
  ADP Chat URL: https://wss.lke.cloud.tencent.com/adp/v2/chat
  ...
============================================================
✓ NapCat 连接成功 | 机器人QQ: 12345678 | 昵称: ...
Bridge 服务就绪，等待消息...
INFO:     Uvicorn running on http://0.0.0.0:8080
✓ NapCat 反向 WebSocket 已连接 | from=127.0.0.1:xxxxx
```

---

## ⚙️ NapCatQQ 配置

NapCat 需要开启 **HTTP 服务器**（Bridge → NapCat 发消息用）和 **反向 WebSocket 客户端**（NapCat → Bridge 推消息）。

编辑 NapCat 的 OneBot11 配置文件（路径形如 `/data/napcat/data/config/onebot11_<uin>.json`）：

```json
{
  "network": {
    "httpServers": [
      {
        "name": "adp-bridge-http",
        "enable": true,
        "host": "127.0.0.1",
        "port": 3001,
        "enableForcePush": true,
        "messagePostFormat": "array",
        "token": ""
      }
    ],
    "websocketClients": [
      {
        "name": "adp-bridge-ws",
        "enable": true,
        "url": "ws://127.0.0.1:8080/onebot/v11/ws",
        "messagePostFormat": "array",
        "reportSelfMessage": false,
        "token": ""
      }
    ]
  }
}
```

> 📝 **Note**:
> 1. **HTTP 端口默认 3001**，避开本机常见的 3000 端口冲突（如果已被其他服务占用，可改成别的，并在 `.env` 同步修改 `NAPCAT_HTTP_URL`）。
> 2. 重启 NapCat 让配置生效。Bridge 的 tmux 会话也要重启（`tmux kill-session -t adp-bridge`）。
> 3. `reportSelfMessage: false` 表示机器人自发消息不进入事件流（避免回环）。

---

## 🔧 配置项说明

完整列表见 [`.env.example`](.env.example)。下面挑重要的：

### ADP 配置

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `ADP_BOT_APP_KEY` | *必填* | ADP 控制台 → 应用 → 发布管理 → 调用信息 → API 管理 |
| `ADP_CHAT_URL` | `https://wss.lke.cloud.tencent.com/adp/v2/chat` | v2 接口地址，一般不用改 |
| `ADP_VISITOR_ID` | `napcat-bridge` | 默认访客 ID（运行时会被覆盖，详见下文） |

### NapCat 配置

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `NAPCAT_HTTP_URL` | `http://127.0.0.1:3001` | NapCat HTTP 服务器地址 |
| `NAPCAT_WS_PORT` | `8080` | Bridge 监听的反向 WS 端口 |
| `NAPCAT_WS_PATH` | `/onebot/v11/ws` | WS 路径 |

### Bridge 行为

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `BRIDGE_TRIGGER_MODE` | `at` | `at`（群 @机器人 触发）/ `always`（所有消息触发） |
| `BRIDGE_ALLOWED_GROUPS` | 空 | 群白名单（逗号分隔），空=不过滤 |
| `BRIDGE_ALLOWED_USERS` | 空 | QQ 白名单（逗号分隔），空=不过滤 |
| `BRIDGE_MAX_HISTORY_TURNS` | `6` | 拼到 user_query 的最近历史轮数；`0`=不传历史 |
| `BRIDGE_MAX_QUERY_LENGTH` | `3000` | user_query 字符上限（超长按 FIFO 丢历史） |
| `BRIDGE_STREAMING_SEND` | `false` | `true`=按 ADP 片段分段发；`false`=攒齐再发 |
| `BRIDGE_STREAMING_BATCH_SIZE` | `50` | 流式模式下每批字符数 |
| `BRIDGE_MAX_MSG_LENGTH` | `4000` | 单条 QQ 消息最大长度（超长自动分段发） |

### 系统提示词

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `BRIDGE_SYSTEM_PROMPTS` | 禁用 Markdown 模板 | 拼到每次请求头部 `[System]` 段；多行用 `\n` |

---

## 🧠 user_query 拼装规则

每次请求，handler 把上游消息拼成如下结构，作为单条 `user_query` 发给 ADP：

```
[System]
你正在通过 QQ 聊天机器人回复用户。
严禁使用 Markdown 格式：不要用 # 标题、**粗体**、*斜体*、代码块、列表符号、链接语法等任何 Markdown 标记。
...
[Context] type=group | from=张三(123456) | group=924777972 | session=group_924777972
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
- **`[Current]`** — 本轮真实消息（已剥离 `@机器人` CQ 码）

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
| 群聊 | `group_<group_id>` | 整群共享上下文，多用户聊也串得起 |
| 私聊 | `qq_<user_id>` | 每用户独立上下文 |

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

## 🛠 部署提示

### tmux 持久化

```bash
tmux new-session -d -s adp-bridge -x 200 -y 50 'cd /data/adp-bridge && .venv/bin/python main.py; exec bash'
tmux capture-pane -t adp-bridge -p    # 看日志
tmux kill-session -t adp-bridge       # 停服务
```

### 端口冲突

3000 端口常被其他服务（如 `node ./dist/index.js`）占用，本项目默认 NapCat HTTP 用 **3001**。如冲突可改 `.env` 的 `NAPCAT_HTTP_URL`，同时改 NapCat 配置文件里的 `httpServers[].port`。

### 端到端自测（不发真实消息）

```python
# test_ws_fake.py
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8080/onebot/v11/ws") as ws:
        await ws.send(json.dumps({
            "post_type": "message",
            "message_type": "private",
            "user_id": 3230772301,
            "self_id": 2020268674,
            "raw_message": "你好",
            "message": [{"type": "text", "data": {"text": "你好"}}],
            "sender": {"user_id": 3230772301, "nickname": "tester"},
        }))
        await asyncio.sleep(15)

asyncio.run(main())
```

---

## ❓ 常见问题

<details>
<summary><b>Q: Bot 在群里发消息不触发回环？</b></summary>

A: OneBot11 配置中 `websocketClients[].reportSelfMessage` 默认 `false`，机器人自发消息不进入事件流，符合预期。
</details>

<details>
<summary><b>Q: 群里有别人 @ 机器人但机器人没反应？</b></summary>

A: 检查三件事：
1. `BRIDGE_ALLOWED_GROUPS` 是否包含该群
2. 触发模式是 `at`（默认值），需要 @ 机器人才响应
3. NapCat 的 WS 是否仍连着（看 Bridge 日志 `NapCat 反向 WebSocket 已连接`）
</details>

<details>
<summary><b>Q: 怎么让机器人不读某群？</b></summary>

A: 不加到 `BRIDGE_ALLOWED_GROUPS` 即可。空 = 全过；填了 = 白名单。
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

A: 默认 `BRIDGE_SYSTEM_PROMPTS` 已经包含"严禁 Markdown"规则。QQ 客户端不渲染 Markdown，看到 `#`/`**` 之类会原样显示。如果你用了自己的 System Prompt 但忘了加这条规则，回复就会出 Markdown 符号。
</details>

---

## 👨‍💻 本地开发

```bash
# 装 dev 依赖
uv pip install -r requirements.txt
# 改完代码后重启
tmux kill-session -t adp-bridge 2>&1
tmux new-session -d -s adp-bridge -x 200 -y 50 'cd /data/adp-bridge && .venv/bin/python main.py; exec bash'

# 看 log
tmux capture-pane -t adp-bridge -p -S -100
```

### 目录结构

```
adp-napcat-bridge/
├── main.py             # FastAPI 入口
├── adp_client.py       # ADP v2 SSE 客户端
├── napcat_client.py    # OneBot v11 HTTP 客户端
├── handler.py          # 消息处理：白名单/触发/历史/user_query 拼装
├── config.py           # .env 配置加载
├── constants.py        # 项目级常量
├── requirements.txt    # 依赖
├── .env.example        # 配置模板
├── .env                # 实际配置（含 AppKey，gitignore）
├── .gitignore
├── LICENSE
└── README.md
```

### 日志 Logger 命名

所有 logger 都通过 `constants.APP_NAME` 生成：

```
adp-napcat-bridge.main      # 启动 / 路由
adp-napcat-bridge.adp       # ADP HTTP 调用
adp-napcat-bridge.napcat    # NapCat HTTP 调用
adp-napcat-bridge.handler   # 消息处理
```

调试时改 `BRIDGE_DEBUG_RAW_EVENT=true` 可打印原始 OneBot 事件。

---

## 📜 License

[MIT](LICENSE) © 2026 adp-napcat-bridge contributors