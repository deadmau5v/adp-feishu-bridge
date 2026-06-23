"""
配置加载模块 — 从环境变量 / .env 文件读取所有配置项
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ADPConfig:
    """腾讯云 ADP 智能体配置（v2 接口）"""
    chat_url: str            # 对话接口地址
    bot_app_key: str         # 应用 AppKey
    visitor_id: str          # 访客 ID（建议用 QQ 号）
    streaming_throttle: int  # 流式回包粒度
    timeout: int             # SSE 请求超时（秒）

    @classmethod
    def from_env(cls) -> "ADPConfig":
        return cls(
            chat_url=os.getenv("ADP_CHAT_URL", "https://wss.lke.cloud.tencent.com/adp/v2/chat"),
            bot_app_key=os.getenv("ADP_BOT_APP_KEY", ""),
            visitor_id=os.getenv("ADP_VISITOR_ID", ""),
            streaming_throttle=int(os.getenv("ADP_STREAMING_THROTTLE", "5")),
            timeout=int(os.getenv("ADP_TIMEOUT", "120")),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.bot_app_key:
            errors.append("ADP_BOT_APP_KEY 未配置")
        return errors


@dataclass(frozen=True)
class NapCatConfig:
    """NapCatQQ 配置"""
    connect_mode: str
    ws_host: str
    ws_port: int
    ws_path: str
    ws_token: str
    webhook_path: str
    webhook_token: str
    http_url: str
    http_token: str

    @classmethod
    def from_env(cls) -> "NapCatConfig":
        return cls(
            connect_mode=os.getenv("NAPCAT_CONNECT_MODE", "reverse_ws"),
            ws_host=os.getenv("NAPCAT_WS_HOST", "0.0.0.0"),
            ws_port=int(os.getenv("NAPCAT_WS_PORT", "8080")),
            ws_path=os.getenv("NAPCAT_WS_PATH", "/onebot/v11/ws"),
            ws_token=os.getenv("NAPCAT_WS_TOKEN", ""),
            webhook_path=os.getenv("NAPCAT_WEBHOOK_PATH", "/onebot/v11/http"),
            webhook_token=os.getenv("NAPCAT_WEBHOOK_TOKEN", ""),
            http_url=os.getenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000"),
            http_token=os.getenv("NAPCAT_HTTP_TOKEN", ""),
        )

    def validate(self) -> list[str]:
        errors = []
        if self.connect_mode not in ("reverse_ws", "webhook"):
            errors.append(f"NAPCAT_CONNECT_MODE 仅支持 reverse_ws / webhook，当前值: {self.connect_mode}")
        if not self.http_url:
            errors.append("NAPCAT_HTTP_URL 未配置")
        return errors


@dataclass(frozen=True)
class BridgeConfig:
    """Bridge 服务行为配置"""
    trigger_mode: str
    allowed_groups: list[str]
    allowed_users: list[str]
    streaming_send: bool
    streaming_batch_size: int
    max_msg_length: int
    log_level: str
    debug_raw_event: bool
    # 多轮上下文：拼到 user_query 里的历史轮数（0=不传历史）
    max_history_turns: int
    # 拼好的 user_query 最大字符数（超过按 FIFO 丢历史）
    max_query_length: int
    # 系统提示词列表：拼到 user_query 头部 [System] 段，每行一条
    system_prompts: list[str]

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        def _split(val: str) -> list[str]:
            return [x.strip() for x in val.split(",") if x.strip()]

        def _split_lines(val: str) -> list[str]:
            return [ln.strip() for ln in val.replace("\\n", "\n").splitlines() if ln.strip()]

        return cls(
            trigger_mode=os.getenv("BRIDGE_TRIGGER_MODE", "at"),
            allowed_groups=_split(os.getenv("BRIDGE_ALLOWED_GROUPS", "")),
            allowed_users=_split(os.getenv("BRIDGE_ALLOWED_USERS", "")),
            streaming_send=os.getenv("BRIDGE_STREAMING_SEND", "false").lower() in ("true", "1", "yes"),
            streaming_batch_size=int(os.getenv("BRIDGE_STREAMING_BATCH_SIZE", "50")),
            max_msg_length=int(os.getenv("BRIDGE_MAX_MSG_LENGTH", "4000")),
            log_level=os.getenv("BRIDGE_LOG_LEVEL", "INFO"),
            debug_raw_event=os.getenv("BRIDGE_DEBUG_RAW_EVENT", "false").lower() in ("true", "1", "yes"),
            max_history_turns=int(os.getenv("BRIDGE_MAX_HISTORY_TURNS", "6")),
            max_query_length=int(os.getenv("BRIDGE_MAX_QUERY_LENGTH", "3000")),
            system_prompts=_split_lines(os.getenv("BRIDGE_SYSTEM_PROMPTS", "")),
        )

    def validate(self) -> list[str]:
        errors = []
        if self.trigger_mode not in ("at", "always"):
            errors.append(f"BRIDGE_TRIGGER_MODE 仅支持 at / always，当前值: {self.bridge.trigger_mode}")
        return errors