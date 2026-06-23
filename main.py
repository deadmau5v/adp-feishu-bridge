"""
ADP-NapCatQQ Bridge 服务主程序

支持两种消息接收模式（通过 NAPCAT_CONNECT_MODE 配置）：
  1. reverse_ws（推荐）— NapCatQQ 主动连接本服务的 WebSocket
  2. webhook          — NapCatQQ 向本服务 POST 事件

启动后：
  - 监听 NapCatQQ 推送的消息事件
  - 调用腾讯云 ADP HTTP SSE 接口获取智能体回复
  - 通过 NapCatQQ HTTP API 将回复发送给用户
"""

import asyncio
import json
import logging
import sys

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from config import ADPConfig, NapCatConfig, BridgeConfig
from adp_client import ADPClient
from napcat_client import NapCatClient
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
napcat_config = NapCatConfig.from_env()
bridge_config = BridgeConfig.from_env()

setup_logging(bridge_config.log_level, bridge_config.debug_raw_event)
logger = logging.getLogger(f"{APP_NAME}.main")

adp_client = ADPClient(adp_config)
napcat_client = NapCatClient(napcat_config)
handler = MessageHandler(adp_client, napcat_client, bridge_config)


# ────────────────────── FastAPI ──────────────────────

app = FastAPI(title=APP_NAME, version=APP_VERSION, description=APP_DESCRIPTION)


@app.on_event("startup")
async def startup():
    """启动时检查配置 + 验证 NapCat 连接"""
    errors = adp_config.validate() + napcat_config.validate() + bridge_config.validate()
    if errors:
        for e in errors:
            logger.error("配置错误: %s", e)
        logger.error("配置校验失败，请检查 .env 文件，程序退出")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("ADP-NapCatQQ Bridge 启动中...")
    logger.info("  连接模式:     %s", napcat_config.connect_mode)
    logger.info("  ADP Chat URL: %s", adp_config.chat_url)
    logger.info("  ADP AppKey:   %s***%s", adp_config.bot_app_key[:4], adp_config.bot_app_key[-4:] if len(adp_config.bot_app_key) > 8 else "**")
    logger.info("  ADP Visitor:  %s", adp_config.visitor_id)
    logger.info("  NapCat HTTP:  %s", napcat_config.http_url)
    logger.info("  触发模式:     %s", bridge_config.trigger_mode)
    logger.info("  流式发送:     %s", bridge_config.streaming_send)
    logger.info("  白名单群:     %s", bridge_config.allowed_groups or "全部")
    logger.info("  白名单用户:   %s", bridge_config.allowed_users or "全部")
    logger.info("=" * 60)

    # 尝试验证 NapCat 连接
    try:
        login_info = await napcat_client.get_login_info()
        if login_info and login_info.get("status") == "ok":
            data = login_info.get("data", {})
            logger.info("✓ NapCat 连接成功 | 机器人QQ: %s | 昵称: %s",
                        data.get("user_id"), data.get("nickname"))
        else:
            logger.warning("⚠ NapCat 连接验证未返回 ok，请检查 NAPCAT_HTTP_URL 和 NAPCAT_HTTP_TOKEN")
    except Exception as e:
        logger.warning("⚠ NapCat 连接验证失败: %s（服务仍会启动，发消息时可能报错）", e)

    logger.info("Bridge 服务就绪，等待消息...")


@app.on_event("shutdown")
async def shutdown():
    """关闭时清理资源"""
    logger.info("Bridge 服务关闭中...")
    await adp_client.close()
    await napcat_client.close()
    logger.info("资源已清理")


# ────────────────────── 反向 WebSocket ──────────────────────

@app.websocket(napcat_config.ws_path)
async def reverse_ws_endpoint(ws: WebSocket):
    """
    反向 WebSocket 端点 — NapCatQQ 作为客户端连接这里。

    NapCatQQ 配置:
      websocketClients:
        - enable: true
          url: ws://<本服务IP>:<NAPCAT_WS_PORT><NAPCAT_WS_PATH>
          token: <NAPCAT_WS_TOKEN>（如果有）
    """
    # 验证 token
    if napcat_config.ws_token:
        auth = ws.headers.get("authorization", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:]
        # OneBot 反向 WS 也可能在 query 参数中传 access_token
        if not token:
            token = ws.query_params.get("access_token", "")
        if token != napcat_config.ws_token:
            logger.warning("反向 WS 连接 token 验证失败，拒绝连接")
            await ws.close(code=4401)
            return

    await ws.accept()
    client_addr = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"
    logger.info("✓ NapCat 反向 WebSocket 已连接 | from=%s", client_addr)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("收到非 JSON 数据: %s", raw[:200])
                continue

            # OneBot v11 反向 WS 可能包含两种消息:
            # 1. 事件推送 (有 post_type 字段)
            # 2. API 调用响应 (有 echo / retcode 字段)
            if "post_type" in event:
                if bridge_config.debug_raw_event:
                    logger.debug("收到事件: %s", json.dumps(event, ensure_ascii=False)[:500])
                # 异步处理，不阻塞 WS 接收
                asyncio.create_task(handler.handle_event(event))
            elif "retcode" in event:
                # API 响应，忽略
                pass
            else:
                if bridge_config.debug_raw_event:
                    logger.debug("收到未知类型消息: %s", json.dumps(event, ensure_ascii=False)[:200])

    except WebSocketDisconnect:
        logger.info("NapCat 反向 WebSocket 断开 | from=%s", client_addr)
    except Exception as e:
        logger.error("反向 WebSocket 异常: %s", e)


# ────────────────────── Webhook (HTTP POST) ──────────────────────

@app.post(napcat_config.webhook_path)
async def webhook_endpoint(request: Request):
    """
    HTTP Webhook 端点 — NapCatQQ 向这里 POST 事件。

    NapCatQQ 配置:
      httpClients:
        - enable: true
          url: http://<本服务IP>:<端口><NAPCAT_WEBHOOK_PATH>
          token: <NAPCAT_WEBHOOK_TOKEN>（如果有）
    """
    # 验证 token
    if napcat_config.webhook_token:
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token:
            token = request.headers.get("x-access-token", "")
        if token != napcat_config.webhook_token:
            return JSONResponse(status_code=401, content={"status": "failed", "message": "token 验证失败"})

    body = await request.body()
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"status": "failed", "message": "invalid json"})

    if "post_type" in event:
        if bridge_config.debug_raw_event:
            logger.debug("Webhook 收到事件: %s", json.dumps(event, ensure_ascii=False)[:500])
        asyncio.create_task(handler.handle_event(event))

    return JSONResponse({"status": "ok"})


# ────────────────────── 健康检查 ──────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "adp-napcat-bridge"}


@app.get("/")
async def root():
    return {
        "service": "adp-napcat-bridge",
        "version": "1.0.0",
        "connect_mode": napcat_config.connect_mode,
        "endpoints": {
            "reverse_ws": f"ws://{napcat_config.ws_host}:{napcat_config.ws_port}{napcat_config.ws_path}",
            "webhook": napcat_config.webhook_path,
            "health": "/health",
        },
    }


# ────────────────────── 启动 ──────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=napcat_config.ws_host,
        port=napcat_config.ws_port,
        log_level=bridge_config.log_level.lower(),
    )
