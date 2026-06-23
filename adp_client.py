"""
腾讯云 ADP 智能体 v2 客户端

接口文档: https://cloud.tencent.com/document/product/1759/129202
请求地址: https://wss.lke.cloud.tencent.com/adp/v2/chat
鉴权方式: bot_app_key（即文档中的 AppKey，从应用发布管理 → 调用信息 → API管理获取）

SSE 事件流:
  - request_ack:        请求确认
  - response.created:   响应开始
  - message.added:      新增消息（thought/reply/tool_call...）
  - content.added:      新增内容段
  - text.delta:         文本增量 (Type=reply 时即用户可见的最终回复)
  - text.replace:       文本替换（如回复需要修正）
  - message.processing: 消息处理中
  - message.done:       消息处理完成（Message.Contents 含最终完整内容）
  - response.completed: 响应完成
  - reference.added:    引文信息
  - quote_info.added:   角标信息
  - error:              错误事件
  - done:               流结束（data: [DONE]）
"""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from config import ADPConfig
from constants import APP_NAME

logger = logging.getLogger(f"{APP_NAME}.adp")


@dataclass
class ADPEvent:
    """ADP SSE 事件（流式）"""
    event_type: str          # text.delta / message.done / error / done 等
    content: str             # 文本增量内容（text.delta 用）
    final_reply: str         # 最终完整回复（message.done 且 Type=reply 时填入）
    raw: dict                # 原始 JSON
    is_final: bool           # 是否为流结束
    message_type: str = ""   # 所属 message 的 Type：reply / thought / tool_call
    message_id: str = ""     # 所属 message 的 MessageId


class ADPClient:
    """ADP v2 对话 SSE 客户端"""

    def __init__(self, config: ADPConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat_stream(
        self,
        content: str,
        session_id: str,
        visitor_id: str | None = None,
    ) -> AsyncIterator[ADPEvent]:
        """
        流式调用 ADP v2 对话接口。

        :param content:    用户消息文本
        :param session_id: 会话 ID（与 conversation_id 复用）
        :param visitor_id: 访客 ID（覆盖配置中的默认值；推荐传实际发消息的 QQ）
        :yield:            ADPEvent 事件流
        """
        if not self.config.bot_app_key:
            raise ValueError("ADP_BOT_APP_KEY 未配置，无法调用对话接口")

        payload = {
            "RequestId": str(uuid.uuid4()),
            "ConversationId": session_id,
            "AppKey": self.config.bot_app_key,
            "VisitorId": visitor_id or self.config.visitor_id,
            "Contents": [{"Type": "text", "Text": content}],
            "Incremental": True,
            "Stream": "enable",
            "StreamingThrottle": self.config.streaming_throttle,
        }

        client = await self.get_client()
        logger.info("调用 ADP v2 | session=%s | content=%s", session_id, content[:80])

        # ADP 同一请求会推送多个 message（thought / tool_call / reply），
        # 各自有自己的 MessageId。text.delta / text.replace 事件只带 MessageId
        # 不带 Type，所以需要在 chat_stream 内部维护 message_id → type 映射，
        # 再把 text.* 事件的 message_type 填好供下游判断是否要累积。
        msg_type_map: dict[str, str] = {}

        try:
            async with client.stream(
                "POST",
                self.config.chat_url,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.error("ADP HTTP 非 200 | status=%s | body=%s", resp.status_code, body[:500])
                    yield ADPEvent("error", f"[ADP HTTP {resp.status_code}]", "", {}, True)
                    return

                event_type = ""
                data_buffer = ""

                async for line in resp.aiter_lines():
                    line = line.rstrip("\r\n")

                    if not line:
                        if data_buffer:
                            ev = self._handle_sse_event(event_type, data_buffer, msg_type_map)
                            if ev:
                                yield ev
                                if ev.is_final:
                                    return
                        event_type = ""
                        data_buffer = ""
                        continue

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buffer += line[5:].strip()

                if data_buffer:
                    ev = self._handle_sse_event(event_type, data_buffer, msg_type_map)
                    if ev:
                        yield ev

        except httpx.ConnectError as e:
            logger.error("ADP 连接失败: %s", e)
            yield ADPEvent("error", "[连接 ADP 失败]", "", {}, True)
        except httpx.ReadTimeout:
            logger.error("ADP 读取超时")
            yield ADPEvent("error", "[ADP 响应超时]", "", {}, True)
        except Exception as e:
            logger.exception("ADP 调用异常")
            yield ADPEvent("error", f"[ADP 调用异常: {e}]", "", {}, True)

    def _handle_sse_event(
        self,
        event_type: str,
        data_str: str,
        msg_type_map: dict[str, str],
    ) -> ADPEvent | None:
        """处理单个 SSE 事件。msg_type_map 会被 message.added / message.done 更新。"""
        if data_str == "[DONE]":
            return ADPEvent("done", "", "", {}, True)

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.warning("ADP 返回非 JSON: %s", data_str[:200])
            return None

        kind = data.get("Type") or event_type or "unknown"

        # message.added 提前告知这是 thought / reply / tool_call
        if kind == "message.added":
            msg = data.get("Message", {}) or {}
            mid = msg.get("MessageId", "")
            mtype = msg.get("Type", "")
            if mid and mtype:
                msg_type_map[mid] = mtype
            return None

        if kind == "text.delta":
            mid = data.get("MessageId", "")
            mtype = msg_type_map.get(mid, "")
            return ADPEvent("text.delta", data.get("Text", ""), "", data, False,
                            message_type=mtype, message_id=mid)

        if kind == "text.replace":
            mid = data.get("MessageId", "")
            mtype = msg_type_map.get(mid, "")
            return ADPEvent("text.replace", data.get("Text", ""), "", data, False,
                            message_type=mtype, message_id=mid)

        if kind == "message.done":
            msg = data.get("Message", {})
            mid = msg.get("MessageId", "")
            mtype = msg.get("Type", "")
            if mid and mtype:
                msg_type_map[mid] = mtype
            reply_text = self._extract_reply_text(msg) if mtype == "reply" else ""
            if reply_text:
                return ADPEvent("message.done", "", reply_text, data, False,
                                message_type=mtype, message_id=mid)
            return None

        if kind == "response.completed":
            return ADPEvent("response.completed", "", "", data, False)

        if kind == "error":
            err = data.get("Error", {})
            msg = err.get("Message", "未知错误")
            code = err.get("Code", "")
            logger.error("ADP error 事件 | code=%s | msg=%s", code, msg)
            return ADPEvent("error", f"[ADP {code}] {msg}", "", data, True)

        if kind in ("request_ack", "response.created", "content.added",
                    "message.processing", "reference.added", "quote_info.added"):
            return None

        return None

    @staticmethod
    def _extract_reply_text(message: dict) -> str:
        """从 message.done 的 Message 字段提取 reply 类型的纯文本"""
        if message.get("Type") != "reply":
            return ""
        parts = []
        for c in message.get("Contents", []) or []:
            if c.get("Type") == "text":
                parts.append(c.get("Text", ""))
        return "".join(parts).strip()

    async def chat(self, content: str, session_id: str, visitor_id: str | None = None) -> str:
        """
        非流式：只收集 ``Type=reply`` 的消息内容作为最终回复。

        ADP v2 智能体在 thought / tool_call 阶段也会推 text.delta，
        这些是中间过程（思考/工具结果），对用户不可见；只有 reply 类型
        message 的 text.delta / message.done 携带的 Contents[0].Text
        才是真正给用户看的。

        :param content:    用户消息
        :param session_id: 会话 ID
        :param visitor_id: 访客 ID（覆盖配置中的默认值）
        :return:           完整 reply 文本；没收到 reply 时返回 ""
        """
        reply_buf: list[str] = []
        last_reply: str = ""
        saw_reply_message: bool = False

        async for ev in self.chat_stream(content, session_id, visitor_id=visitor_id):
            if ev.event_type == "error":
                return ev.content
            if ev.message_type == "reply":
                saw_reply_message = True
                if ev.event_type == "text.delta" and ev.content:
                    reply_buf.append(ev.content)
                elif ev.event_type == "text.replace" and ev.content is not None:
                    # 增量模式下偶尔出现：重置 buffer
                    reply_buf = [ev.content]
                elif ev.event_type == "message.done" and ev.final_reply:
                    last_reply = ev.final_reply

        # 优先取 message.done 的 final_reply（完整版），其次取 text.delta 累积版
        if last_reply:
            return last_reply
        if saw_reply_message and reply_buf:
            return "".join(reply_buf).strip()
        return ""