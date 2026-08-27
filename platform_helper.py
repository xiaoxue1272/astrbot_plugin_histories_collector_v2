"""平台辅助类基类与工厂函数。

PlatformHelper (基类):
  - get_chain / get_sender / get_group: 平台接口。
  - _convert: 默认框架组件 → Enhanced 转换。
    子类覆写此方法实现平台特定转换，
    失败时回退到 super()._convert()。
"""

from astrbot.api import logger

from dataclasses import dataclass

from astrbot.core.message.components import (
    At,
    BaseMessageComponent,
    Face,
    File,
    Forward,
    Image,
    Json,
    Music,
    Node,
    Nodes,
    Plain,
    Record,
    Reply,
    Share,
    Video,
)
from astrbot.core.platform import AstrMessageEvent

from data.plugins.astrbot_plugin_histories_collector_v2.enhanced import (
    EnhancedComponent,
    EnhancedFace,
    EnhancedFile,
    EnhancedForward,
    EnhancedImage,
    EnhancedJson,
    EnhancedMention,
    EnhancedMentionAll,
    EnhancedMusic,
    EnhancedNode,
    EnhancedNodes,
    EnhancedPlain,
    EnhancedReply,
    EnhancedShare,
    EnhancedVideo,
    EnhancedVoice,
)
from data.plugins.astrbot_plugin_histories_collector_v2.download_manager import DownloadManager


@dataclass
class CollectorConfig:
    """平台辅助类共享配置。

    Args:
        max_nesting_depth: 消息链最大嵌套深度。
    """

    max_nesting_depth: int = 3


class PlatformHelper:
    """平台辅助类基类。

    子类覆写 get_chain() 返回已完整处理的 Enhanced 消息链，
    覆写 _convert() 实现平台特定的组件转换。
    """

    def __init__(self, event: AstrMessageEvent, config: CollectorConfig, download_manager: DownloadManager):
        self._event = event
        self._config = config
        self._download_manager = download_manager

    async def get_chain(self) -> list[EnhancedComponent]:
        """构建 Enhanced 消息链。子类覆写。"""
        results: list[EnhancedComponent] = []
        for comp in self._event.get_messages():
            enhanced = await self._convert(comp)
            if enhanced is not None:
                results.append(enhanced)
        return results

    async def get_sender(self) -> dict:
        return {
            "id": self._event.get_sender_id(),
            "name": self._event.get_sender_name(),
        }

    async def get_group(self) -> dict:
        group_obj = self._event.message_obj.group
        return {
            "id": self._event.get_group_id(),
            "name": group_obj.group_name if group_obj else None,
        }

    # ── 组件转换 ──

    async def _convert(
        self,
        component: BaseMessageComponent,
        ctx: object = None,
    ) -> EnhancedComponent | None:
        """将框架消息组件转换为 Enhanced 类型。

        子类覆写实现平台特定转换，失败时回退到 super()._convert()。

        Args:
            component: 框架消息组件。
            ctx: 平台特定上下文（如 OneBot segment dict）。

        Returns:
            Enhanced 组件，不支持的类型返回 None。
        """
        if isinstance(component, Plain):
            return EnhancedPlain(text=component.text)
        if isinstance(component, At):
            if component.qq == "all":
                return EnhancedMentionAll()
            return EnhancedMention(
                id=str(component.qq),
                name=component.name or "",
                nickname=component.name or "",
            )
        if isinstance(component, Image):
            return EnhancedImage(url=getattr(component, "url", ""))
        if isinstance(component, File):
            return EnhancedFile(name=getattr(component, "name", ""), url=getattr(component, "url", ""))
        if isinstance(component, Video):
            return EnhancedVideo(url=getattr(component, "url", ""))
        if isinstance(component, Record):
            return EnhancedVoice(url=getattr(component, "url", ""), text=getattr(component, "text", None))
        if isinstance(component, Face):
            return EnhancedFace(id=str(getattr(component, "id", "")))
        if isinstance(component, Reply):
            messages = []
            for comp in getattr(component, "content", []):
                enhanced_comp = await self._convert(comp)
                if enhanced_comp is not None:
                    messages.append(enhanced_comp)
            return EnhancedReply(
                id=getattr(component, "id", None),
                sender_id=getattr(component, "sender_id", None),
                sender_nickname=getattr(component, "sender_nickname", None),
                time=getattr(component, "time", None),
                messages=messages
            )
        if isinstance(component, Json):
            return EnhancedJson(data=getattr(component, "data", None))
        if isinstance(component, Forward):
            return EnhancedForward(id=getattr(component, "id", None))
        if isinstance(component, Nodes):
            messages = []
            for node in getattr(component, "nodes", []):
                enhanced_node = await self._convert(node)
                if enhanced_node is not None:
                    messages.append(enhanced_node)
            return EnhancedNodes(messages=messages)
        if isinstance(component, Node):
            messages = []
            for comp in getattr(component, "content", []):
                enhanced_comp = await self._convert(comp)
                if enhanced_comp is not None:
                    messages.append(enhanced_comp)
            return EnhancedNode(
                sender_id=getattr(component, "uin", None),
                sender_name=getattr(component, "name", None),
                time=getattr(component, "time", None),
                messages=messages,
            )
        if isinstance(component, Share):
            return EnhancedShare(
                url=getattr(component, "url", ""),
                title=getattr(component, "title", ""),
                content=getattr(component, "content", ""),
                image=getattr(component, "image", ""),
            )
        if isinstance(component, Music):
            return EnhancedMusic(
                source=getattr(component, "source", None),
                id=getattr(component, "id", None),
                url=getattr(component, "url", None),
                audio=getattr(component, "audio", None),
                title=getattr(component, "title", None),
                content=getattr(component, "content", None),
                image=getattr(component, "image", None),
            )
        logger.debug(f"不支持的框架组件类型: {type(component).__name__}")
        return None


class DefaultPlatformHelper(PlatformHelper):
    """默认平台辅助类，使用框架提供的 API。"""


def create_platform_helper(
    event: AstrMessageEvent,
    config: CollectorConfig,
    download_manager: DownloadManager,
) -> PlatformHelper:
    """根据 event 类型创建对应的平台辅助类实例。

    Args:
        event: AstrMessageEvent 实例。
        config: CollectorConfig 实例。
        download_manager: 下载管理器实例。

    Returns:
        平台辅助类实例。
    """
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

    from data.plugins.astrbot_plugin_histories_collector_v2.platforms.aiocqhttp import AiocqhttpPlatformHelper

    if isinstance(event, AiocqhttpMessageEvent):
        return AiocqhttpPlatformHelper(event, config, download_manager)
    return DefaultPlatformHelper(event, config, download_manager)
