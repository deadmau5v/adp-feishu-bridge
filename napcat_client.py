"""
NapCatQQ 客户端 — 通过 OneBot v11 HTTP API 发送消息

依赖 NapCatQQ 开启 HTTP 服务器：
  - host: 127.0.0.1
  - port: 3000（与 .env 中 NAPCAT_HTTP_URL 对应）
  - token: 与 .env 中 NAPCAT_HTTP_TOKEN 对应
"""

import logging
from typing import Any

import httpx

from config import NapCatConfig
from constants import APP_NAME

logger = logging.getLogger(f"{APP_NAME}.napcat")


class NapCatClient:
    """NapCatQQ OneBot v11 HTTP API 客户端"""

    def __init__(self, config: NapCatConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.config.http_token:
                headers["Authorization"] = f"Bearer {self.config.http_token}"
            self._client = httpx.AsyncClient(
                base_url=self.config.http_url,
                headers=headers,
                timeout=httpx.Timeout(30, connect=5),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _call(self, action: str, params: dict[str, Any]) -> dict | None:
        """调用 OneBot v11 HTTP API"""
        client = await self.get_client()
        try:
            resp = await client.post(f"/{action}", json=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ok":
                logger.warning("NapCat API 返回非 ok | action=%s | resp=%s", action, data)
            return data
        except Exception as e:
            logger.error("NapCat API 调用失败 | action=%s | error=%s", action, e)
            return None

    async def send_private_msg(self, user_id: int, message: str) -> dict | None:
        """发送私聊消息"""
        return await self._call("send_private_msg", {
            "user_id": user_id,
            "message": message,
        })

    async def send_group_msg(self, group_id: int, message: str) -> dict | None:
        """发送群消息"""
        return await self._call("send_group_msg", {
            "group_id": group_id,
            "message": message,
        })

    async def send_msg(
        self,
        message: str,
        user_id: int | None = None,
        group_id: int | None = None,
    ) -> dict | None:
        """
        统一发送消息。
        - group_id 不为空 → 群消息
        - 否则 → 私聊消息
        """
        if group_id:
            return await self.send_group_msg(group_id, message)
        elif user_id:
            return await self.send_private_msg(user_id, message)
        else:
            logger.error("send_msg 缺少 user_id 和 group_id")
            return None

    async def get_login_info(self) -> dict | None:
        """获取机器人登录信息（用于启动时验证连接）"""
        return await self._call("get_login_info", {})

    async def send_msg_segments(
        self,
        message: str,
        user_id: int | None = None,
        group_id: int | None = None,
        max_length: int = 4000,
    ) -> None:
        """
        发送消息，超长自动分段。

        :param message:   消息文本
        :param user_id:   私聊目标 QQ
        :param group_id:  群号
        :param max_length: 单条消息最大长度
        """
        if not message:
            return

        # 分段
        segments = []
        if len(message) <= max_length:
            segments = [message]
        else:
            for i in range(0, len(message), max_length):
                segments.append(message[i:i + max_length])

        for i, seg in enumerate(segments):
            if i > 0:
                # 分段之间稍微间隔，避免风控（简单的 await 即可）
                import asyncio
                await asyncio.sleep(0.3)
            await self.send_msg(seg, user_id=user_id, group_id=group_id)
