"""Platform helper base and factory.

PlatformHelper (base):
  - get_chain / get_sender / get_group: platform interface.
  - _convert: default framework component → Enhanced conversion.
    Subclasses override this for platform-specific conversion,
    falling back to super()._convert() as needed.
"""

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
from data.plugins.astrbot_plugin_histories_collector_v2.file_manager import FileManager


@dataclass
class CollectorConfig:
    """Shared configuration for platform helpers.

    Args:
        max_nesting_depth: Maximum message chain nesting depth.
        max_file_size_mb: Maximum file size in MB for downloads.
    """

    max_nesting_depth: int = 3
    max_file_size_mb: int = 50


class PlatformHelper:
    """Base platform helper.

    Subclasses override get_chain() to return fully-hydrated Enhanced chains,
    and _convert() for platform-specific component conversion.
    """

    def __init__(self, event: AstrMessageEvent, config: CollectorConfig):
        self._event = event
        self._config = config
        self._file_manager = FileManager(
            max_file_size_mb=config.max_file_size_mb,
        )

    async def get_chain(self) -> list[EnhancedComponent]:
        """Build the Enhanced chain. Override in platform subclasses."""
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

    # ── Conversion ──

    async def _convert(
        self,
        component: BaseMessageComponent,
        ctx: object = None,
    ) -> EnhancedComponent | None:
        """Convert a framework component to Enhanced.

        Override in subclasses for platform-specific conversion.
        Fall back to super()._convert() for unsupported types.

        Args:
            component: Framework message component.
            ctx: Optional platform-specific context (e.g. OneBot segment dict).

        Returns:
            Enhanced component, or None for unsupported types.
        """
        if isinstance(component, Plain):
            return EnhancedPlain(text=component.text)
        if isinstance(component, At):
            if component.qq == "all":
                return EnhancedMentionAll()
            return EnhancedMention(id=str(component.qq), name=component.name or "")
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
        return None


class DefaultPlatformHelper(PlatformHelper):
    """Default platform helper using framework-provided APIs."""


def create_platform_helper(event: AstrMessageEvent, config: CollectorConfig) -> PlatformHelper:
    """Factory that returns the correct platform helper for the given event.

    Args:
        event: AstrMessageEvent instance.
        config: CollectorConfig instance.

    Returns:
        A platform helper instance.
    """
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

    from data.plugins.astrbot_plugin_histories_collector_v2.platforms.aiocqhttp import AiocqhttpPlatformHelper

    if isinstance(event, AiocqhttpMessageEvent):
        return AiocqhttpPlatformHelper(event, config)
    return DefaultPlatformHelper(event, config)
