"""平台辅助类基类与工厂函数。

PlatformHelper (基类):
  - get_chain: 统一入口（构建链 → 类型过滤 → 媒体下载）。
  - get_sender / get_group: 平台接口。
  - _convert: 按组件类型分发到已注册的转换器。
    子类覆写 ``_build_chain()`` 实现平台解析，
    或通过 ``register_converter()`` 扩展新的组件类型。
"""

import json
from dataclasses import dataclass

from astrbot.api import logger
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
from data.plugins.astrbot_plugin_histories_collector_v2.download_manager import (
    DownloadManager,
)
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


@dataclass
class CollectorConfig:
    """平台辅助类共享配置。

    Args:
        max_nesting_depth: 消息链最大嵌套深度。
        parse_types: 允许解析的组件类型列表；空表示全部解析。
        download_types: 允许下载的媒体类型列表；空表示全部下载。
    """

    max_nesting_depth: int = 3
    parse_types: list[str] | None = None
    download_types: list[str] | None = None


class PlatformHelper:
    """平台辅助类基类。

    子类覆写 ``_build_chain()`` 构建原始消息链，
    通过 ``register_converter()`` 扩展或覆盖组件转换器。

    解析类型过滤（``parse_types``）与媒体下载（``download_types``）
    统一在 ``get_chain()`` 中处理，新增平台实现类只需实现
    ``_build_chain()``，无需重复判断。
    """

    def __init__(
        self,
        event: AstrMessageEvent,
        config: CollectorConfig,
        download_manager: DownloadManager,
    ):
        self._event = event
        self._config = config
        self._download_manager = download_manager

    async def get_chain(self) -> list[EnhancedComponent]:
        """构建 Enhanced 消息链，并统一做类型过滤与媒体下载。

        这是所有平台共用的唯一入口：子类只需覆写 ``_build_chain()``，
        解析类型过滤与媒体下载都在这里集中处理。

        Returns:
            过滤且完成媒体下载的 Enhanced 消息链。
        """
        chain = await self._build_chain()
        return await self.filter_and_download(chain)

    async def _build_chain(self) -> list[EnhancedComponent]:
        """构建原始 Enhanced 消息链（子类覆写，不做类型过滤）。

        Returns:
            未过滤的 Enhanced 消息链。
        """
        results: list[EnhancedComponent] = []
        for comp in self._event.get_messages():
            enhanced = await self._convert(comp)
            if enhanced is not None:
                results.append(enhanced)
        return results

    async def filter_and_download(
        self, chain: list[EnhancedComponent]
    ) -> list[EnhancedComponent]:
        """按 parse_types 过滤消息链，并下载通过过滤的媒体组件。

        递归处理 reply/nodes/node 的子链；下载时直接调用下载器。

        Args:
            chain: 原始 Enhanced 消息链。

        Returns:
            过滤后的消息链（子链同样已过滤）。
        """
        parse_types = self._config.parse_types
        kept: list[EnhancedComponent] = []
        for comp in chain:
            if parse_types and comp.type not in parse_types:
                logger.debug(f"跳过未配置解析的组件: type={comp.type}")
                continue
            if isinstance(comp, EnhancedFile):
                if self._should_download(comp.type):
                    try:
                        await self._download_manager.download_and_cache(comp)
                    except Exception as e:
                        # 单条媒体失败（磁盘满、权限、缓存写盘异常等）不应中断整条消息
                        logger.warning(
                            f"媒体下载失败，跳过该组件: type={comp.type}, {e}"
                        )
                else:
                    logger.debug(f"跳过下载: 类型未启用, type={comp.type}")
            if isinstance(comp, (EnhancedReply, EnhancedNodes, EnhancedNode)):
                comp.messages = await self.filter_and_download(comp.messages or [])
            kept.append(comp)
        return kept

    def _should_download(self, comp_type: str) -> bool:
        """判断某组件类型是否需要下载（download_types 为空表示全部下载）。

        Args:
            comp_type: Enhanced 组件类型（如 image、voice）。

        Returns:
            True 表示需要下载。
        """
        download_types = self._config.download_types
        return not download_types or comp_type in download_types

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
        """按组件类型分发到对应的转换方法。

        每个类型一个独立方法，子类覆写对应方法即可生效，
        未覆写的类型自动走父类默认实现。

        Args:
            component: 框架消息组件。
            ctx: 平台特定上下文（如 OneBot segment dict），按需使用。

        Returns:
            Enhanced 组件，不支持的类型返回 None。
        """
        if isinstance(component, Plain):
            return await self._convert_plain(component, ctx)
        if isinstance(component, At):
            return await self._convert_at(component, ctx)
        if isinstance(component, Image):
            return await self._convert_image(component, ctx)
        if isinstance(component, File):
            return await self._convert_file(component, ctx)
        if isinstance(component, Video):
            return await self._convert_video(component, ctx)
        if isinstance(component, Record):
            return await self._convert_record(component, ctx)
        if isinstance(component, Face):
            return await self._convert_face(component, ctx)
        if isinstance(component, Reply):
            return await self._convert_reply(component, ctx)
        if isinstance(component, Json):
            return await self._convert_json(component, ctx)
        if isinstance(component, Forward):
            return await self._convert_forward(component, ctx)
        if isinstance(component, Nodes):
            return await self._convert_nodes(component, ctx)
        if isinstance(component, Node):
            return await self._convert_node(component, ctx)
        if isinstance(component, Share):
            return await self._convert_share(component, ctx)
        if isinstance(component, Music):
            return await self._convert_music(component, ctx)
        logger.debug(f"不支持的框架组件类型: {type(component).__name__}")
        return None

    # ── 各组件转换器 ──

    async def _convert_plain(
        self, component: Plain, ctx: object = None
    ) -> EnhancedPlain:
        return EnhancedPlain(text=component.text)

    async def _convert_at(
        self, component: At, ctx: object = None
    ) -> EnhancedMention | EnhancedMentionAll:
        if component.qq == "all":
            return EnhancedMentionAll()
        return EnhancedMention(
            id=str(component.qq),
            name=component.name or "",
            nickname=component.name or "",
        )

    async def _convert_image(
        self, component: Image, ctx: object = None
    ) -> EnhancedImage:
        return EnhancedImage(url=getattr(component, "url", ""))

    async def _convert_file(self, component: File, ctx: object = None) -> EnhancedFile:
        return EnhancedFile(url=getattr(component, "url", ""))

    async def _convert_video(
        self, component: Video, ctx: object = None
    ) -> EnhancedVideo:
        return EnhancedVideo(url=getattr(component, "url", ""))

    async def _convert_record(
        self, component: Record, ctx: object = None
    ) -> EnhancedVoice:
        return EnhancedVoice(
            url=getattr(component, "url", ""),
            text=getattr(component, "text", None),
        )

    async def _convert_face(self, component: Face, ctx: object = None) -> EnhancedFace:
        return EnhancedFace(id=str(getattr(component, "id", "")))

    async def _convert_reply(
        self, component: Reply, ctx: object = None
    ) -> EnhancedReply:
        messages: list[EnhancedComponent] = []
        for comp in getattr(component, "chain", []) or []:
            enhanced_comp = await self._convert(comp)
            if enhanced_comp is not None:
                messages.append(enhanced_comp)
        return EnhancedReply(
            id=getattr(component, "id", None),
            sender_id=getattr(component, "sender_id", None),
            sender_nickname=getattr(component, "sender_nickname", None),
            time=getattr(component, "time", None),
            messages=messages,
        )

    async def _convert_json(self, component: Json, ctx: object = None) -> EnhancedJson:
        data = getattr(component, "data", None)
        if data is None:
            return EnhancedJson()
        # 统一序列化为合法 JSON 字符串，与 aiocqhttp 路径保持一致
        return EnhancedJson(data=json.dumps(data, ensure_ascii=False))

    async def _convert_forward(
        self, component: Forward, ctx: object = None
    ) -> EnhancedForward:
        return EnhancedForward(id=getattr(component, "id", None))

    async def _convert_nodes(
        self, component: Nodes, ctx: object = None
    ) -> EnhancedNodes:
        messages: list[EnhancedComponent] = []
        for node in getattr(component, "nodes", []):
            enhanced_node = await self._convert(node)
            if enhanced_node is not None:
                messages.append(enhanced_node)
        return EnhancedNodes(messages=messages)

    async def _convert_node(self, component: Node, ctx: object = None) -> EnhancedNode:
        messages: list[EnhancedComponent] = []
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

    async def _convert_share(
        self, component: Share, ctx: object = None
    ) -> EnhancedShare:
        return EnhancedShare(
            url=getattr(component, "url", ""),
            title=getattr(component, "title", ""),
            content=getattr(component, "content", ""),
            image=getattr(component, "image", ""),
        )

    async def _convert_music(
        self, component: Music, ctx: object = None
    ) -> EnhancedMusic:
        return EnhancedMusic(
            source=getattr(component, "source", None),
            id=getattr(component, "id", None),
            url=getattr(component, "url", None),
            audio=getattr(component, "audio", None),
            title=getattr(component, "title", None),
            content=getattr(component, "content", None),
            image=getattr(component, "image", None),
        )


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
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )
    from data.plugins.astrbot_plugin_histories_collector_v2.platforms.aiocqhttp import (
        AiocqhttpPlatformHelper,
    )

    if isinstance(event, AiocqhttpMessageEvent):
        return AiocqhttpPlatformHelper(event, config, download_manager)
    return DefaultPlatformHelper(event, config, download_manager)
