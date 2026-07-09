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
    visitor_id: str          # 访客 ID（建议用飞书 open_id）
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
class FeishuConfig:
    """飞书自建应用配置"""
    app_id: str              # 飞书应用 App ID
    app_secret: str          # 飞书应用 App Secret
    domain: str              # 飞书域名：feishu / lark
    log_level: str           # 飞书 SDK 日志级别
    debug_raw_event: bool    # 打印原始事件
    bot_open_id: str         # 机器人 open_id（可选；用于群聊识别 @机器人，不填则只能靠"@_user_x 占位"启发式判断）

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        return cls(
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            domain=os.getenv("FEISHU_DOMAIN", "feishu"),
            log_level=os.getenv("FEISHU_LOG_LEVEL", "INFO"),
            debug_raw_event=os.getenv("BRIDGE_DEBUG_RAW_EVENT", "false").lower() in ("true", "1", "yes"),
            bot_open_id=os.getenv("FEISHU_BOT_OPEN_ID", ""),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.app_id:
            errors.append("FEISHU_APP_ID 未配置")
        if not self.app_secret:
            errors.append("FEISHU_APP_SECRET 未配置")
        if self.domain not in ("feishu", "lark"):
            errors.append(f"FEISHU_DOMAIN 仅支持 feishu / lark，当前值: {self.domain}")
        return errors


@dataclass(frozen=True)
class BridgeConfig:
    """Bridge 服务行为配置"""
    trigger_mode: str
    allowed_chats: list[str]    # 飞书 chat_id 白名单（群或私聊），空=不过滤
    allowed_users: list[str]    # 飞书 open_id 白名单，空=不过滤
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
            allowed_chats=_split(os.getenv("BRIDGE_ALLOWED_CHATS", "")),
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
            errors.append(f"BRIDGE_TRIGGER_MODE 仅支持 at / always，当前值: {self.trigger_mode}")
        return errors
