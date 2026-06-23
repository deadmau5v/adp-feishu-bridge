"""
消息处理器 — 核心业务逻辑

接收 OneBot v11 事件 → 判断是否需要响应 → 拼装 user_query（带上下文/触发人/历史）
→ 调用 ADP → 回复消息
"""

import asyncio
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from adp_client import ADPClient
from napcat_client import NapCatClient
from config import BridgeConfig
from constants import APP_NAME

logger = logging.getLogger(f"{APP_NAME}.handler")


@dataclass
class HistoryTurn:
    """一条多轮上下文记录"""
    role: str          # "user" / "assistant"
    speaker: str       # 群聊时的发言者名字 / 私聊时的对方昵称
    text: str          # 消息文本
    ts: float = field(default_factory=time.time)

    def render(self) -> str:
        return f"[{self.role}] {self.speaker}: {self.text}"


class MessageHandler:
    """处理 OneBot v11 消息事件"""

    def __init__(
        self,
        adp: ADPClient,
        napcat: NapCatClient,
        bridge: BridgeConfig,
    ):
        self.adp = adp
        self.napcat = napcat
        self.bridge = bridge
        # 正在处理中的会话，防止同一用户连续触发
        self._processing: set[str] = set()
        # 每个 session 的最近历史（按 FIFO 淘汰）
        # key = session_id（不是 visitor_id；私聊按 qq_ 隔离，群聊按 group_ 隔离）
        self._history: dict[str, Deque[HistoryTurn]] = {}

    # ────────────────── 主入口 ──────────────────

    async def handle_event(self, event: dict) -> None:
        """
        处理 OneBot v11 事件。
        """
        post_type = event.get("post_type")

        if post_type != "message":
            return

        # 提取消息信息
        message_type = event.get("message_type")  # private / group
        user_id = event.get("user_id", 0)
        group_id = event.get("group_id")  # 群消息才有
        raw_message = event.get("raw_message", "")
        sender = event.get("sender", {})
        sender_name = sender.get("card") or sender.get("nickname", str(user_id))

        # 白名单过滤
        if self.bridge.allowed_users and str(user_id) not in self.bridge.allowed_users:
            return
        if group_id and self.bridge.allowed_groups and str(group_id) not in self.bridge.allowed_groups:
            return

        # 提取纯文本消息
        text = self._extract_text(event)
        if not text.strip():
            return

        # 触发判断
        if not self._should_respond(event, text):
            return

        # 去掉 @机器人 的 CQ 码，得到纯内容
        clean_text = self._strip_at(text)
        if not clean_text.strip():
            return

        # 构造 session_id — 私聊按 qq_ 隔离，群聊按 group_ 隔离
        if group_id:
            session_key = f"group_{group_id}"
        else:
            session_key = f"qq_{user_id}"
        session_id = self._make_session_id(session_key)

        # 防止并发重复处理
        if session_id in self._processing:
            logger.info("会话 %s 正在处理中，跳过", session_id)
            return
        self._processing.add(session_id)

        try:
            logger.info(
                "处理消息 | type=%s | user=%s(%s) | group=%s | text=%s",
                message_type, user_id, sender_name, group_id, clean_text[:80],
            )
            # 拼装 user_query（带上下文元数据 + 多轮历史）
            user_query = self._build_user_query(
                clean_text=clean_text,
                sender_name=sender_name,
                user_id=user_id,
                group_id=group_id,
                message_type=message_type,
                session_id=session_id,
            )

            # 记录到 history（在调用 ADP 之前）
            self._append_history(session_id, HistoryTurn(
                role="user", speaker=sender_name, text=clean_text,
            ))

            if self.bridge.streaming_send:
                reply = await self._call_adp_stream(user_query, session_id,
                                                     user_id, group_id)
            else:
                reply = await self._call_adp_batch(user_query, session_id,
                                                   user_id, group_id)

            # 把 ADP 回复也写进 history
            if reply:
                assistant_speaker = "丁真"  # 机器人自己
                self._append_history(session_id, HistoryTurn(
                    role="assistant", speaker=assistant_speaker, text=reply,
                ))

        except Exception:
            logger.exception("处理消息异常 | user=%s", user_id)
            try:
                await self.napcat.send_msg_segments(
                    "[处理消息时发生错误，请稍后重试]",
                    user_id=user_id, group_id=group_id,
                    max_length=self.bridge.max_msg_length,
                )
            except Exception:
                pass
        finally:
            self._processing.discard(session_id)

    # ────────────────── ADP 调用 ──────────────────

    async def _call_adp_batch(self, content, session_id, user_id, group_id) -> str:
        """非流式：等 ADP 完整回复后再发送"""
        visitor_id = self._make_visitor_id(user_id, group_id)
        reply = await self.adp.chat(content, session_id, visitor_id=visitor_id)
        if reply:
            await self.napcat.send_msg_segments(
                reply,
                user_id=user_id,
                group_id=group_id,
                max_length=self.bridge.max_msg_length,
            )
            logger.info("回复发送完成 | user=%s | visitor=%s | reply_len=%d",
                        user_id, visitor_id, len(reply))
        return reply

    async def _call_adp_stream(self, content, session_id, user_id, group_id) -> str:
        """流式：收到 ADP 片段就攒批发送"""
        buffer = ""
        batch_size = self.bridge.streaming_batch_size
        visitor_id = self._make_visitor_id(user_id, group_id)

        async for event in self.adp.chat_stream(content, session_id,
                                                  visitor_id=visitor_id):
            if event.event_type == "error":
                await self.napcat.send_msg_segments(
                    event.content,
                    user_id=user_id, group_id=group_id,
                    max_length=self.bridge.max_msg_length,
                )
                return event.content

            if event.content:
                buffer += event.content
                while len(buffer) >= batch_size:
                    batch, buffer = buffer[:batch_size], buffer[batch_size:]
                    await self.napcat.send_msg_segments(
                        batch,
                        user_id=user_id, group_id=group_id,
                        max_length=self.bridge.max_msg_length,
                    )

            if event.is_final:
                break

        if buffer.strip():
            await self.napcat.send_msg_segments(
                buffer,
                user_id=user_id, group_id=group_id,
                max_length=self.bridge.max_msg_length,
            )
        logger.info("流式回复完成 | user=%s | visitor=%s | reply_len=%d",
                    user_id, visitor_id, len(buffer))
        return buffer

    # ────────────────── user_query 拼装 ──────────────────

    def _build_user_query(
        self,
        clean_text: str,
        sender_name: str,
        user_id: int,
        group_id: int | None,
        message_type: str,
        session_id: str,
    ) -> str:
        """
        拼装最终发给 ADP 的 user_query。

        格式：
          [System]               ← 系统提示词（每行一条规则）
          rule 1
          rule 2
          [Context] type=private|group | from=昵称(qq) | group=群号(若有) | session=...
          [History]              ← 多轮历史
          [user] xxx: ...
          [assistant] 丁真: ...
          ...
          [Current] <clean_text>
        """
        # 系统提示词
        system_block = ""
        if self.bridge.system_prompts:
            system_block = "[System]\n" + "\n".join(self.bridge.system_prompts)

        # 上游上下文元数据
        ctx_bits = [f"type={message_type}"]
        ctx_bits.append(f"from={sender_name}({user_id})")
        if group_id:
            ctx_bits.append(f"group={group_id}")
        ctx_bits.append(f"session={session_id}")
        ctx_line = "[Context] " + " | ".join(ctx_bits)

        # 多轮历史
        history_block = ""
        if self.bridge.max_history_turns > 0:
            turns = list(self._history.get(session_id, []))[-self.bridge.max_history_turns:]
            if turns:
                history_block = "[History]\n" + "\n".join(t.render() for t in turns)

        # 当前消息
        current_block = f"[Current] {clean_text}"

        # 顺序拼接
        parts = []
        if system_block:
            parts.append(system_block)
        parts.append(ctx_line)
        if history_block:
            parts.append(history_block)
        parts.append(current_block)
        query = "\n".join(parts)

        # 字符上限：超过则从 history 头部丢（system + ctx + current 永远保留）
        max_len = self.bridge.max_query_length
        if len(query) > max_len:
            query = self._trim_to_length(query, history_block, current_block,
                                         ctx_line, system_block, max_len)

        logger.debug("user_query 长度=%d | history_turns=%d | system_rules=%d",
                     len(query), len(self._history.get(session_id, [])),
                     len(self.bridge.system_prompts))
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
        """
        query 超过 max_len 时按 FIFO 丢历史。
        system + ctx + current 永远保留；超长时丢 history 头部。
        """
        # 至少保留 system + ctx + current
        prefix_len = (len(system_block) + 1 if system_block else 0) + len(ctx_line) + 1
        suffix_len = len(current_block) + 1
        must_keep_len = prefix_len + suffix_len
        if must_keep_len >= max_len:
            # current 本身就超长 — 截断 current
            budget = max_len - prefix_len - len("[Current] ") - 4
            truncated_current = current_block[:max(0, budget)] + "..."
            parts = []
            if system_block:
                parts.append(system_block)
            parts.append(ctx_line)
            parts.append(f"[Current] {truncated_current}")
            return "\n".join(parts)

        # history 可用预算
        budget = max_len - must_keep_len
        if not history_block or budget <= 0:
            parts = []
            if system_block:
                parts.append(system_block)
            parts.append(ctx_line)
            parts.append(current_block)
            return "\n".join(parts)

        # 解析 history 为各 turn，按行倒序保留
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
        else:
            # 调整 maxlen
            dq.maxlen = max(self.bridge.max_history_turns, 1)
        dq.append(turn)

    # ────────────────── 工具方法 ──────────────────

    def _should_respond(self, event: dict, text: str) -> bool:
        """判断是否应该响应这条消息"""
        if self.bridge.trigger_mode == "always":
            return True

        # at 模式：私聊始终响应，群聊仅 @机器人 时响应
        message_type = event.get("message_type")
        if message_type == "private":
            return True

        if message_type == "group":
            # 检查消息中是否 @了机器人
            # OneBot v11 中 @ 表现为 CQ:at,qq=bot_qq
            return "[CQ:at" in text and self._is_at_bot(event)

        return False

    def _is_at_bot(self, event: dict) -> bool:
        """检查是否 @了机器人"""
        self_id = event.get("self_id", 0)
        # 检查 message 数组中的 at 段
        message = event.get("message", [])
        if isinstance(message, list):
            for seg in message:
                if isinstance(seg, dict) and seg.get("type") == "at":
                    if str(seg.get("data", {}).get("qq", "")) == str(self_id):
                        return True
        # 检查 raw_message 中的 CQ 码
        raw = event.get("raw_message", "")
        return f"[CQ:at,qq={self_id}]" in raw

    def _extract_text(self, event: dict) -> str:
        """从 OneBot v11 事件中提取纯文本 + CQ 码"""
        # 优先使用 raw_message（字符串形式，含 CQ 码）
        raw = event.get("raw_message", "")
        if raw:
            return raw

        # 从 message 数组拼接
        message = event.get("message", [])
        if isinstance(message, list):
            parts = []
            for seg in message:
                if isinstance(seg, dict):
                    if seg.get("type") == "text":
                        parts.append(seg.get("data", {}).get("text", ""))
                    elif seg.get("type") == "at":
                        qq = seg.get("data", {}).get("qq", "")
                        parts.append(f"[CQ:at,qq={qq}]")
                    else:
                        parts.append(f"[CQ:{seg.get('type', 'unknown')}]")
            return "".join(parts)
        return ""

    def _strip_at(self, text: str) -> str:
        """去掉 @机器人 的 CQ 码，只留实际内容"""
        # 移除所有 CQ:at 码
        cleaned = re.sub(r"\[CQ:at,qq=\d+\]", "", text)
        return cleaned.strip()

    def _make_session_id(self, key: str) -> str:
        """
        根据 key 生成合法的 session_id。
        ADP 要求: ^[a-zA-Z0-9_-]{2,64}$
        """
        # 确保只包含合法字符
        safe = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
        # 截断到 64 字符以内
        return safe[:64]

    @staticmethod
    def _make_visitor_id(user_id: int, group_id: int | None) -> str:
        """
        生成访客 ID：
          - 群聊：group_<group_id>   （整群共享上下文）
          - 私聊：qq_<user_id>       （每用户独立上下文）
        ADP v2 的 VisitorId 无长度限制，但为安全起见只允许 [a-zA-Z0-9_-]。
        """
        if group_id:
            return f"group_{group_id}"
        return f"qq_{user_id}"
