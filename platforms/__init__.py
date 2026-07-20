from data.plugins.astrbot_plugin_histories_collector_v2.platforms.base import (
    ParserConfig,
    PlatformMessageParser,
)
from data.plugins.astrbot_plugin_histories_collector_v2.platforms.aiocqhttp import AiocqhttpMessageParser

__all__ = ["ParserConfig", "PlatformMessageParser", "AiocqhttpMessageParser", "create_parser"]


def create_parser(event, config: ParserConfig) -> PlatformMessageParser:
    """根据 event 类型创建对应的平台消息解析器实例。

    Args:
        event: AstrMessageEvent 实例。
        config: 全局解析器配置。

    Returns:
        平台对应的 PlatformMessageParser 子类实例。
    """
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

    if isinstance(event, AiocqhttpMessageEvent):
        return AiocqhttpMessageParser(config, event)
    return PlatformMessageParser(config, event)
