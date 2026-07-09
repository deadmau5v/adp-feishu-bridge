"""
ADP-Feishu Bridge 服务主程序

通过 lark-oapi SDK 的 WebSocket 长连接接收飞书消息事件，无需公网回调地址。

启动后：
  - 后台线程跑飞书长连接（SDK 内部负责断线重连、心跳）
  - asyncio loop 跑 FastAPI（健康检查 + 元信息接口）
  - 收到飞书消息后 → handler → ADP → 飞书 REST 发回
"""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from config import ADPConfig, FeishuConfig, BridgeConfig
from adp_client import ADPClient
from feishu_client import FeishuClient
from handler import MessageHandler
from constants import APP_NAME, APP_VERSION, APP_DESCRIPTION

# ────────────────────── 日志 ──────────────────────


def setup_logging(level: str, debug_raw: bool):
    fmt = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        stream=sys.stdout,
    )
    if debug_raw:
        logging.getLogger(APP_NAME).setLevel(logging.DEBUG)


# ────────────────────── 全局对象 ──────────────────────

adp_config = ADPConfig.from_env()
feishu_config = FeishuConfig.from_env()
bridge_config = BridgeConfig.from_env()

setup_logging(bridge_config.log_level, bridge_config.debug_raw_event)
logger = logging.getLogger(f"{APP_NAME}.main")

adp_client = ADPClient(adp_config)
feishu_client: FeishuClient | None = None
handler: MessageHandler | None = None


# ────────────────────── FastAPI lifespan ──────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：配置校验 → 创建 client/handler → 启动飞书长连接线程"""
    global feishu_client, handler

    errors = adp_config.validate() + feishu_config.validate() + bridge_config.validate()
    if errors:
        for e in errors:
            logger.error("配置错误: %s", e)
        logger.error("配置校验失败，请检查 .env 文件，程序退出")
        sys.exit(1)

    feishu_client = FeishuClient(feishu_config, on_message=_dispatch)
    handler = MessageHandler(adp_client, feishu_client, bridge_config, feishu_config)

    logger.info("=" * 60)
    logger.info("ADP-Feishu Bridge 启动中...")
    logger.info("  App ID:        %s***", feishu_config.app_id[:6])
    logger.info("  Domain:        %s", feishu_config.domain)
    logger.info("  Bot open_id:   %s", feishu_config.bot_open_id or "(未配置，群聊 @识别 失效)")
    logger.info("  ADP Chat URL:  %s", adp_config.chat_url)
    logger.info("  ADP AppKey:    %s***%s", adp_config.bot_app_key[:4],
                adp_config.bot_app_key[-4:] if len(adp_config.bot_app_key) > 8 else "**")
    logger.info("  触发模式:      %s", bridge_config.trigger_mode)
    logger.info("  流式发送:      %s", bridge_config.streaming_send)
    logger.info("  白名单群:      %s", bridge_config.allowed_chats or "全部")
    logger.info("  白名单用户:    %s", bridge_config.allowed_users or "全部")
    logger.info("=" * 60)

    # 后台线程跑飞书长连接（SDK 内部阻塞 main；不阻塞 asyncio）
    feishu_client.start_ws_in_thread()

    logger.info("Bridge 服务就绪，等待飞书消息...")

    try:
        yield
    finally:
        logger.info("Bridge 服务关闭中...")
        if feishu_client:
            await feishu_client.close()
        await adp_client.close()
        logger.info("资源已清理")


async def _dispatch(event: dict) -> None:
    """飞书事件分发入口（在 FeishuClient 的后台线程 → asyncio 任务中触发）"""
    if handler is None:
        return
    try:
        await handler.handle_event(event)
    except Exception:
        logger.exception("handle_event 未捕获异常")


# ────────────────────── FastAPI ──────────────────────

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": APP_NAME}


@app.get("/")
async def root():
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "channel": "feishu",
        "domain": feishu_config.domain,
        "endpoints": {
            "health": "/health",
        },
    }


# ────────────────────── 启动 ──────────────────────


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(__import__("os").getenv("BRIDGE_PORT", "8080"))
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=bridge_config.log_level.lower(),
    )
