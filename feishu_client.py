"""
飞书客户端 — 消息接收 + 发送

接收：通过 lark-oapi SDK 的 WebSocket 长连接接收 im.message.receive_v1 事件，
       无需公网 IP / 域名 / 证书，本地直接跑。
发送：调用 OpenAPI POST /open-apis/im/v1/messages 主动发文本消息。

飞书应用配置（开发者后台 → 应用 → 事件订阅）：
  - 订阅方式：使用长连接接收事件
  - 权限：       im:message, im:message.group_at_msg, im:message.p2p_msg,
               im:message:send_as_bot
  - 事件：       im.message.receive_v1
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import httpx

from config import FeishuConfig
from constants import APP_NAME

logger = logging.getLogger(f"{APP_NAME}.feishu")

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
TENANT_TOKEN_URL = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"


class FeishuClient:
    """飞书 IM 客户端：长连接收事件 + REST 主动发消息"""

    def __init__(self, config: FeishuConfig, on_message):
        """
        :param config:    飞书应用配置
        :param on_message: 收到 im.message.receive_v1 事件时的回调，签名:
                           async def on_message(event: dict) -> None
                           event 结构见 _normalize_event 输出。
        """
        self.config = config
        self._on_message = on_message
        self._http: httpx.AsyncClient | None = None
        self._tenant_token: str | ""
        self._token_expire_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._ws_thread: threading.Thread | None = None
        self._ws_cli: Any = None
        self._stop_event = threading.Event()

    # ────────────────── 生命周期 ──────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端、停掉长连接线程"""
        self._stop_event.set()
        if self._ws_cli is not None:
            try:
                self._ws_cli.stop()
            except Exception:
                pass
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    def start_ws(self) -> None:
        """
        启动飞书长连接（阻塞当前线程）。建议在 FastAPI 启动后由 lifespan /
        后台任务调用，本服务用 threading.Thread 跑，不阻塞 asyncio loop。
        """
        import lark_oapi as lark
        from lark_oapi.event.dispatcher import EventDispatcherHandler

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(
                self._on_message_sync,
            )
            .build()
        )

        log_level = (
            lark.LogLevel.DEBUG
            if self.config.log_level.upper() == "DEBUG"
            else lark.LogLevel.INFO
        )

        cli = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=handler,
            log_level=log_level,
        )
        self._ws_cli = cli
        logger.info(
            "飞书长连接启动中 | app_id=%s*** | domain=%s",
            self.config.app_id[:6],
            self.config.domain,
        )
        # SDK 内部 run_forever；本进程退出时由 _stop_event 标记，close() 调 stop()
        cli.start()

    def start_ws_in_thread(self) -> threading.Thread:
        """后台线程跑长连接（FastAPI 主进程不阻塞）"""
        t = threading.Thread(
            target=self.start_ws,
            name="feishu-ws",
            daemon=True,
        )
        t.start()
        self._ws_thread = t
        return t

    # ────────────────── 事件处理 ──────────────────

    def _on_message_sync(self, data: Any) -> None:
        """
        飞书 SDK 回调（同步线程），转成 asyncio 任务处理。
        """
        try:
            event = self._extract_event(data)
        except Exception:
            logger.exception("解析飞书事件失败")
            return

        if not event:
            return

        if self.config.debug_raw_event:
            logger.debug("飞书事件: %s", json.dumps(event, ensure_ascii=False)[:500])

        # 推到主 asyncio loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(event), loop)
        else:
            # 没有运行中的 loop：兜底同步跑（不会并发，仅在测试场景出现）
            logger.warning("未找到运行中的 asyncio loop，回调将被丢弃")

    @staticmethod
    def _extract_event(data: Any) -> dict | None:
        """
        把 lark_oapi 的 P2ImMessageReceiveV1 数据对象转成 dict 风格事件。

        输出结构：
          {
            "message_id":   "om_xxx",
            "chat_id":      "oc_xxx",          # 会话 ID（私聊/群）
            "chat_type":    "p2p" | "group",
            "sender_open_id": "ou_xxx",         # 发送者 open_id
            "sender_user_id": "u_xxx" 或 "",    # 发送者 user_id（与 app 通信过才会有）
            "sender_name":  "张三",
            "message_type": "text",
            "text":         "纯文本（已剥离 @_user_x 占位）",
            "mentions":     [{"key":"@_user_1","open_id":"ou_xxx","name":"张三"}, ...],
            "raw":          {...}              # 原始 message 字段
          }
        """
        try:
            event = data.event
            msg = event.message
            sender = event.sender
        except AttributeError:
            logger.warning("飞书事件结构异常: %r", data)
            return None

        message_type = getattr(msg, "message_type", "") or ""
        chat_id = getattr(msg, "chat_id", "") or ""
        chat_type = getattr(msg, "chat_type", "") or ""
        message_id = getattr(msg, "message_id", "") or ""

        # 发送者
        sender_id_obj = getattr(sender, "sender_id", None)
        sender_open_id = (
            getattr(sender_id_obj, "open_id", "") if sender_id_obj else ""
        )
        sender_user_id = (
            getattr(sender_id_obj, "user_id", "") if sender_id_obj else ""
        )
        sender_name = ""

        # 文本 + mentions
        text = ""
        mentions: list[dict[str, str]] = []
        if message_type == "text":
            content_str = getattr(msg, "content", "") or "{}"
            try:
                content_obj = json.loads(content_str)
                text = (content_obj.get("text") or "").strip()
            except json.JSONDecodeError:
                logger.warning("飞书 message.content 非 JSON: %s", content_str[:200])
                text = content_str

            for m in getattr(msg, "mentions", []) or []:
                m_id = getattr(m, "id", None)
                mentions.append({
                    "key": getattr(m, "key", "") or "",
                    "open_id": getattr(m_id, "open_id", "") if m_id else "",
                    "user_id": getattr(m_id, "user_id", "") if m_id else "",
                    "name": getattr(m, "name", "") or "",
                })

        return {
            "message_id": message_id,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "sender_open_id": sender_open_id,
            "sender_user_id": sender_user_id,
            "sender_name": sender_name or sender_open_id,
            "message_type": message_type,
            "text": text,
            "mentions": mentions,
            "raw": data,
        }

    # ────────────────── 主动发消息 ──────────────────

    async def get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=FEISHU_API_BASE,
                timeout=httpx.Timeout(20, connect=5),
            )
        return self._http

    async def _get_tenant_token(self) -> str:
        """获取/缓存 tenant_access_token"""
        import time
        async with self._token_lock:
            if self._tenant_token and time.time() < self._token_expire_at - 60:
                return self._tenant_token

            client = await self.get_http()
            resp = await client.post(
                TENANT_TOKEN_URL,
                json={
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(
                    f"获取 tenant_access_token 失败: {data.get('code')} {data.get('msg')}"
                )
            self._tenant_token = data["tenant_access_token"]
            self._token_expire_at = time.time() + int(data.get("expire", 7200))
            return self._tenant_token

    async def _post(
        self,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        token = await self._get_tenant_token()
        client = await self.get_http()
        resp = await client.post(
            path,
            params=params or {},
            json=json_body or {},
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            data = resp.json()
        except json.JSONDecodeError:
            resp.raise_for_status()
            return {}
        if resp.status_code >= 400 or data.get("code", 0) not in (0,):
            logger.error(
                "飞书 API 失败 | path=%s | status=%s | resp=%s",
                path, resp.status_code, json.dumps(data, ensure_ascii=False)[:300],
            )
        return data

    async def send_text(
        self,
        text: str,
        chat_id: str | None = None,
        open_id: str | None = None,
    ) -> dict | None:
        """
        发送文本消息。
        - 群聊：传 chat_id
        - 私聊：传 open_id（receive_id_type=open_id）
        """
        if not text:
            return None
        if not chat_id and not open_id:
            logger.error("send_text 缺少 chat_id / open_id")
            return None

        receive_id = chat_id or open_id
        receive_id_type = "chat_id" if chat_id else "open_id"

        return await self._post(
            "/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json_body={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )

    async def send_msg(
        self,
        text: str,
        chat_id: str | None = None,
        open_id: str | None = None,
    ) -> dict | None:
        """统一发送接口：handler 只需要传 chat_id 或 open_id"""
        return await self.send_text(text, chat_id=chat_id, open_id=open_id)

    async def send_msg_segments(
        self,
        text: str,
        chat_id: str | None = None,
        open_id: str | None = None,
        max_length: int = 4000,
    ) -> None:
        """
        发送消息，超长自动分段（飞书单条消息 30KB 上限，留足余量用 4000 字符）。

        飞书没有"中间停顿防风控"的强需求，但仍保留 0.3s 间隔避免被识别为刷屏。
        """
        if not text:
            return

        if len(text) <= max_length:
            segments = [text]
        else:
            segments = [text[i:i + max_length] for i in range(0, len(text), max_length)]

        for i, seg in enumerate(segments):
            if i > 0:
                await asyncio.sleep(0.3)
            await self.send_msg(seg, chat_id=chat_id, open_id=open_id)

    # ────────────────── 元信息 ──────────────────

    async def get_bot_info(self) -> dict | None:
        """获取机器人自身的 open_id（用于群聊识别 @机器人）"""
        data = await self._post(
            "/bot/v3/info",
        )
        if data.get("code") == 0:
            bot = data.get("bot", {})
            return {
                "open_id": bot.get("open_id", ""),
                "app_name": bot.get("app_name", ""),
            }
        return None
