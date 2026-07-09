"""
消息处理器 — 核心业务逻辑

接收飞书事件（im.message.receive_v1）→ 判断是否需要响应 → 拼装 user_query
（带上下文/触发人/历史）→ 调用 ADP → 回复消息
"""

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from adp_client import ADPClient
from feishu_client import FeishuClient
from config import BridgeConfig, FeishuConfig
from constants import APP_NAME

logger = logging.getLogger(f"{APP_NAME}.handler")


@dataclass
class HistoryTurn:
    """一条多轮上下文记录"""

    role: str  # "user" / "assistant"
    speaker: str  # 发言者名字
    text: str  # 消息文本
    ts: float = field(default_factory=time.time)

    def render(self) -> str:
        return f"[{self.role}] {self.speaker}: {self.text}"


class MessageHandler:
    """处理飞书 im.message.receive_v1 事件"""

    def __init__(
        self,
        adp: ADPClient,
        feishu: FeishuClient,
        bridge: BridgeConfig,
        feishu_cfg: FeishuConfig,
    ):
        self.adp = adp
        self.feishu = feishu
        self.bridge = bridge
        self.feishu_cfg = feishu_cfg
        # 正在处理中的会话，防止同一会话连续触发
        self._processing: set[str] = set()
        # 每个 session 的最近历史（按 FIFO 淘汰）
        self._history: dict[str, Deque[HistoryTurn]] = {}

    # ────────────────── 主入口 ──────────────────

    async def handle_event(self, event: dict) -> None:
        """
        处理飞书事件（feishu_client._extract_event 的输出结构）。
        """
        chat_type = event.get("chat_type", "")  # p2p / group
        if chat_type not in ("p2p", "group"):
            return

        chat_id = event.get("chat_id", "")
        sender_open_id = event.get("sender_open_id", "")
        sender_name = event.get("sender_name", "") or sender_open_id
        text = event.get("text", "")
        mentions = event.get("mentions", [])

        # 白名单过滤
        if (
            self.bridge.allowed_users
            and sender_open_id not in self.bridge.allowed_users
        ):
            return
        if self.bridge.allowed_chats and chat_id not in self.bridge.allowed_chats:
            return

        if not text.strip():
            return

        # 触发判断
        if not self._should_respond(chat_type, text, mentions):
            return

        # 去掉 @占位符，得到纯内容
        clean_text = self._strip_at(text, mentions)
        if not clean_text.strip():
            return

        # 构造 session_id
        session_key = (
            f"group_{chat_id}" if chat_type == "group" else f"feishu_{sender_open_id}"
        )
        session_id = self._make_session_id(session_key)

        # 防止并发重复处理
        if session_id in self._processing:
            logger.info("会话 %s 正在处理中，跳过", session_id)
            return
        self._processing.add(session_id)

        # 群聊需要 reply target = chat_id；私聊用 open_id
        reply_chat_id = chat_id if chat_type == "group" else None
        reply_open_id = None if chat_type == "group" else sender_open_id

        try:
            logger.info(
                "处理消息 | type=%s | user=%s(%s) | chat=%s | text=%s",
                chat_type,
                sender_open_id,
                sender_name,
                chat_id,
                clean_text[:80],
            )
            user_query = self._build_user_query(
                clean_text=clean_text,
                sender_name=sender_name,
                user_id=sender_open_id,
                chat_id=chat_id,
                chat_type=chat_type,
                session_id=session_id,
            )

            self._append_history(
                session_id,
                HistoryTurn(
                    role="user",
                    speaker=sender_name,
                    text=clean_text,
                ),
            )

            if self.bridge.streaming_send:
                reply = await self._call_adp_stream(
                    user_query,
                    session_id,
                    chat_id=reply_chat_id,
                    open_id=reply_open_id,
                    user_open_id=sender_open_id,
                )
            else:
                reply = await self._call_adp_batch(
                    user_query,
                    session_id,
                    chat_id=reply_chat_id,
                    open_id=reply_open_id,
                    user_open_id=sender_open_id,
                )

            if reply:
                self._append_history(
                    session_id,
                    HistoryTurn(
                        role="assistant",
                        speaker="丁真",
                        text=reply,
                    ),
                )

        except Exception:
            logger.exception("处理消息异常 | user=%s", sender_open_id)
            try:
                await self.feishu.send_msg_segments(
                    "[处理消息时发生错误，请稍后重试]",
                    chat_id=reply_chat_id,
                    open_id=reply_open_id,
                    max_length=self.bridge.max_msg_length,
                )
            except Exception:
                pass
        finally:
            self._processing.discard(session_id)

    # ────────────────── ADP 调用 ──────────────────

    async def _call_adp_batch(
        self, content, session_id, chat_id, open_id, user_open_id
    ) -> str:
        """非流式：等 ADP 完整回复后再发送"""
        visitor_id = self._make_visitor_id(user_open_id, chat_id)
        reply = await self.adp.chat(content, session_id, visitor_id=visitor_id)
        if reply:
            await self.feishu.send_msg_segments(
                reply,
                chat_id=chat_id,
                open_id=open_id,
                max_length=self.bridge.max_msg_length,
            )
            logger.info(
                "回复发送完成 | user=%s | visitor=%s | reply_len=%d",
                user_open_id,
                visitor_id,
                len(reply),
            )
        return reply

    async def _call_adp_stream(
        self, content, session_id, chat_id, open_id, user_open_id
    ) -> str:
        """流式：仅发送 Type=reply 消息的 text.delta 分段，其他类型静默丢弃"""
        buffer = ""
        batch_size = self.bridge.streaming_batch_size
        visitor_id = self._make_visitor_id(user_open_id, chat_id)
        last_reply: str = ""

        async for event in self.adp.chat_stream(
            content, session_id, visitor_id=visitor_id
        ):
            if event.event_type == "error":
                await self.feishu.send_msg_segments(
                    event.content,
                    chat_id=chat_id,
                    open_id=open_id,
                    max_length=self.bridge.max_msg_length,
                )
                return event.content

            if event.message_type != "reply":
                continue

            if event.event_type == "message.done" and event.final_reply:
                last_reply = event.final_reply

            if event.content:
                buffer += event.content
                while len(buffer) >= batch_size:
                    batch, buffer = buffer[:batch_size], buffer[batch_size:]
                    await self.feishu.send_msg_segments(
                        batch,
                        chat_id=chat_id,
                        open_id=open_id,
                        max_length=self.bridge.max_msg_length,
                    )

        if last_reply and (not buffer or last_reply != buffer):
            tail = last_reply
            if buffer and last_reply.startswith(buffer):
                tail = last_reply[len(buffer) :]
            if tail.strip():
                await self.feishu.send_msg_segments(
                    tail,
                    chat_id=chat_id,
                    open_id=open_id,
                    max_length=self.bridge.max_msg_length,
                )
                buffer = last_reply
        elif buffer.strip() and not last_reply:
            await self.feishu.send_msg_segments(
                buffer,
                chat_id=chat_id,
                open_id=open_id,
                max_length=self.bridge.max_msg_length,
            )

        logger.info(
            "流式回复完成 | user=%s | visitor=%s | reply_len=%d",
            user_open_id,
            visitor_id,
            len(buffer),
        )
        return buffer

    # ────────────────── user_query 拼装 ──────────────────

    def _build_user_query(
        self,
        clean_text: str,
        sender_name: str,
        user_id: str,
        chat_id: str,
        chat_type: str,
        session_id: str,
    ) -> str:
        """
        拼装最终发给 ADP 的 user_query。

        格式：
          [System]                ← 系统提示词
          rule 1
          rule 2
          [Context] type=p2p|group | from=昵称(open_id) | chat=oc_xxx | session=...
          [History]               ← 多轮历史
          [user] xxx: ...
          [assistant] 丁真: ...
          ...
          [Current] <clean_text>
        """
        system_block = ""
        if self.bridge.system_prompts:
            system_block = "[System]\n" + "\n".join(self.bridge.system_prompts)

        ctx_bits = [f"type={chat_type}"]
        ctx_bits.append(f"from={sender_name}({user_id})")
        ctx_bits.append(f"chat={chat_id}")
        ctx_bits.append(f"session={session_id}")
        ctx_line = "[Context] " + " | ".join(ctx_bits)

        history_block = ""
        if self.bridge.max_history_turns > 0:
            turns = list(self._history.get(session_id, []))[
                -self.bridge.max_history_turns :
            ]
            if turns:
                history_block = "[History]\n" + "\n".join(t.render() for t in turns)

        current_block = f"[Current] {clean_text}"

        parts = []
        if system_block:
            parts.append(system_block)
        parts.append(ctx_line)
        if history_block:
            parts.append(history_block)
        parts.append(current_block)
        query = "\n".join(parts)

        max_len = self.bridge.max_query_length
        if len(query) > max_len:
            query = self._trim_to_length(
                query, history_block, current_block, ctx_line, system_block, max_len
            )

        logger.debug(
            "user_query 长度=%d | history_turns=%d | system_rules=%d",
            len(query),
            len(self._history.get(session_id, [])),
            len(self.bridge.system_prompts),
        )
        return query

    def _trim_to_length(
        self,
        query: str,
        history_block: str,
        current_block: str,
        ctx_line: str,
        system_block: str,
        max_len: int,
    ) -> str:
        """query 超过 max_len 时按 FIFO 丢历史。system + ctx + current 永远保留。"""
        prefix_len = (len(system_block) + 1 if system_block else 0) + len(ctx_line) + 1
        suffix_len = len(current_block) + 1
        must_keep_len = prefix_len + suffix_len
        if must_keep_len >= max_len:
            budget = max_len - prefix_len - len("[Current] ") - 4
            truncated_current = current_block[: max(0, budget)] + "..."
            parts = []
            if system_block:
                parts.append(system_block)
            parts.append(ctx_line)
            parts.append(f"[Current] {truncated_current}")
            return "\n".join(parts)

        budget = max_len - must_keep_len
        if not history_block or budget <= 0:
            parts = []
            if system_block:
                parts.append(system_block)
            parts.append(ctx_line)
            parts.append(current_block)
            return "\n".join(parts)

        lines = [ln for ln in history_block.split("\n") if ln]
        kept: list[str] = []
        for ln in reversed(lines):
            if len(kept) + len(ln) + 1 > budget:
                break
            kept.append(ln)
        kept.reverse()
        new_history = "\n".join(kept) if kept else ""

        parts = []
        if system_block:
            parts.append(system_block)
        parts.append(ctx_line)
        if new_history:
            parts.append(f"[History]\n{new_history}")
        parts.append(current_block)
        return "\n".join(parts)

    # ────────────────── History 管理 ──────────────────

    def _append_history(self, session_id: str, turn: HistoryTurn) -> None:
        dq = self._history.get(session_id)
        if dq is None:
            dq = deque(maxlen=max(self.bridge.max_history_turns, 1))
            self._history[session_id] = dq
        dq.append(turn)

    # ────────────────── 工具方法 ──────────────────

    def _should_respond(self, chat_type: str, text: str, mentions: list[dict]) -> bool:
        """判断是否应该响应这条消息"""
        if self.bridge.trigger_mode == "always":
            return True

        # at 模式：私聊始终响应，群聊仅 @机器人 时响应
        if chat_type == "p2p":
            return True

        if chat_type == "group":
            return self._is_at_bot(mentions)

        return False

    def _is_at_bot(self, mentions: list[dict]) -> bool:
        """检查 mentions 中是否包含机器人"""
        # 优先用配置的 bot_open_id 精确匹配
        bot_open_id = self.feishu_cfg.bot_open_id
        if bot_open_id:
            return any(m.get("open_id") == bot_open_id for m in mentions)
        # 没配置时回退到占位符启发式：飞书 @ 自己时 key 是 @_user_<n>，
        # 但跟其他用户无法区分；只能借助 mentions 第一项并依赖配置
        # —— 强烈建议填写 FEISHU_BOT_OPEN_ID。
        return False

    @staticmethod
    def _strip_at(text: str, mentions: list[dict]) -> str:
        """去掉消息开头的 @占位符（@_user_x），只留实际内容"""
        for m in mentions:
            key = m.get("key", "")
            if key and key in text:
                text = text.replace(key, "")
        return text.strip()

    def _make_session_id(self, key: str) -> str:
        """
        根据 key 生成合法的 session_id。
        ADP 要求: ^[a-zA-Z0-9_-]{2,64}$
        """
        safe = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
        return safe[:64]

    @staticmethod
    def _make_visitor_id(user_open_id: str, chat_id: str | None) -> str:
        """
        生成访客 ID：
          - 群聊：group_<chat_id>   （整群共享上下文）
          - 私聊：feishu_<open_id>  （每用户独立上下文）
        """
        if chat_id:
            return f"group_{chat_id}"
        return f"feishu_{user_open_id}"
