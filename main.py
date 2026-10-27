import time

from snowflake import SnowflakeGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.star.filter.event_message_type import EventMessageType
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterType
from data.plugins.astrbot_plugin_histories_collector_v2.config import (
    HistoriesCollectorConfig,
)
from data.plugins.astrbot_plugin_histories_collector_v2.download_manager import (
    DownloadManager,
)
from data.plugins.astrbot_plugin_histories_collector_v2.es_helper import ESHelper
from data.plugins.astrbot_plugin_histories_collector_v2.group_filter import GroupFilter
from data.plugins.astrbot_plugin_histories_collector_v2.platform_helper import (
    CollectorConfig,
    create_platform_helper,
)
from data.plugins.astrbot_plugin_histories_collector_v2.search_tool import SearchEsTool
from data.plugins.astrbot_plugin_histories_collector_v2.summary import build_summary
from data.plugins.astrbot_plugin_histories_collector_v2.utils import PLUGIN_NAME


@register(
    PLUGIN_NAME,
    "xiaoxue1272",
    "Astrbot 全平台群消息收集器V2(ES版)",
    "v0.3.0-SNAPSHOT",
)
class HistoriesCollectorV2Plugin(Star):
    """全平台群消息收集器，将消息结构化存入 Elasticsearch。

    支持黑白名单过滤。消息链完整解析，含媒体文件下载缓存。
    """

    config: HistoriesCollectorConfig
    group_filter: GroupFilter
    es_helper: ESHelper
    id_generator: SnowflakeGenerator
    collector_config: CollectorConfig
    download_manager: DownloadManager

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = HistoriesCollectorConfig(config)
        self.id_generator = SnowflakeGenerator(instance=0)
        # 预先置 None，确保 initialize 失败时 terminate 与事件处理不会抛 AttributeError
        self.group_filter = None
        self.es_helper = None
        self.collector_config = None
        self.download_manager = None

        # ESHelper 先构造（不连接）并注入 LLM 工具，连接在 initialize 中建立。
        # 工具在此注册：add_llm_tools 会自动解析归属模块路径，且早于
        # star_manager 绑定循环，激活/停用/卸载由框架统一管理。
        self.es_helper = ESHelper(self.config.es_config)
        self.context.add_llm_tools(SearchEsTool(es_helper=self.es_helper))

    async def initialize(self) -> None:
        """连接 Elasticsearch 并初始化索引。"""
        logger.info("HistoriesCollectorV2 插件正在初始化...")

        self.collector_config = CollectorConfig(
            max_nesting_depth=self.config.max_nesting_depth,
            parse_types=self.config.parse_types,
            download_types=self.config.download_types,
        )
        self.download_manager = DownloadManager(
            max_file_size_mb=self.config.max_file_size_mb,
        )

        self.group_filter = GroupFilter(self.config.group_filter)
        # es_helper 已在 __init__ 创建并注册给 LLM 工具，这里只建立连接
        await self.es_helper.initialize()

        logger.info("HistoriesCollectorV2 插件初始化完成。")

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(PlatformAdapterType.ALL)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理全平台群消息。

        Args:
            event: 跨平台消息事件（仅依赖基类 API，无平台子类依赖）。
        """
        if not self.es_helper or not self.es_helper.is_connected:
            return

        platform_name = event.get_platform_name()
        group_id = event.get_group_id()

        if not self.group_filter.should_collect(platform_name, group_id):
            return

        doc = await self._build_document(event)
        if doc is None:
            return

        # 文档 ID 使用 Snowflake，每次收集生成唯一 ID。
        # 注意：同一条消息被多个平台实例收到或重放时会写入多条文档，
        # 去重依赖 _source 中的 message_id + platform_id + group.id 组合查询。
        doc_id = str(next(self.id_generator))

        try:
            await self.es_helper.save_message(doc_id, doc)
        except Exception as e:
            logger.error(
                f"ES 保存消息失败，消息已丢弃: message_id={event.message_obj.message_id}, {e}"
            )

    @filter.after_message_sent()
    async def on_bot_message_sent(self, event: AstrMessageEvent):
        """收集机器人自己发送到群聊的消息。

        OneBot 不会把机器人自己发出的消息作为群消息事件回推，因此通过
        发送完成钩子获取实际发出的消息链，单独写入 ES。媒体按现有流程
        同步下载，发送后可能有短暂延迟。

        Args:
            event: 当前消息事件（回复阶段的事件，结果尚未被清空）。
        """
        if not self.config.collect_bot_message:
            return
        if not self.es_helper or not self.es_helper.is_connected:
            return
        if event.is_private_chat():
            return

        platform_name = event.get_platform_name()
        group_id = event.get_group_id()
        if not group_id or not self.group_filter.should_collect(
            platform_name, group_id
        ):
            return

        result = event.get_result()
        chain = getattr(result, "chain", None) if result else None
        if not chain:
            return

        helper = create_platform_helper(
            event, self.collector_config, self.download_manager
        )
        enhanced = []
        for comp in chain:
            converted = await helper._convert(comp)
            if converted is not None:
                enhanced.append(converted)
        if not enhanced:
            return
        # 与平台消息链一致：类型过滤 + 媒体下载
        enhanced = await helper.filter_and_download(enhanced)
        if not enhanced:
            return

        self_id = str(event.get_self_id() or "")
        doc = {
            "@timestamp": int(time.time() * 1000),
            "platform": platform_name.strip(),
            "platform_id": event.get_platform_id().strip(),
            # 机器人自己发送的消息拿不到平台 msgId，留空字符串
            "message_id": "",
            "group": await helper.get_group(),
            "sender": {"id": self_id, "name": self_id, "nickname": ""},
            "summary": build_summary(enhanced),
            "types": list(dict.fromkeys(comp.type for comp in enhanced)),
            "messages": [comp.to_dict() for comp in enhanced],
        }

        try:
            await self.es_helper.save_message(str(next(self.id_generator)), doc)
        except Exception as e:
            logger.error(f"ES 保存机器人消息失败: {e}")

    async def _build_document(self, event: AstrMessageEvent) -> dict | None:
        """Build ES document.

        Platform-specific logic (chain building, sender/group, forward summary,
        message chain parsing) is handled uniformly through the platform helper.

        Args:
            event: Cross-platform message event.

        Returns:
            Dict to be written to ES.
        """
        raw = event.message_obj.raw_message
        if not raw:
            return None
        if getattr(raw, "post_type", "").lower() == "notice":
            return None

        helper = create_platform_helper(
            event, self.collector_config, self.download_manager
        )

        group_doc = await helper.get_group()
        sender_doc = await helper.get_sender()
        chain = await helper.get_chain()

        # 跳过空链（系统通知、无法解析的消息）
        if not chain:
            logger.debug(f"消息链为空，跳过: message_id={event.message_obj.message_id}")
            return None

        doc = {
            "@timestamp": int(getattr(raw, "time", event.message_obj.timestamp) * 1000),
            "platform": event.get_platform_name().strip(),
            "platform_id": event.get_platform_id().strip(),
            "message_id": event.message_obj.message_id,
            "group": group_doc,
            "sender": sender_doc,
            "summary": build_summary(chain),
            "types": list(dict.fromkeys(comp.type for comp in chain)),
            "messages": [comp.to_dict() for comp in chain],
        }
        return doc

    async def terminate(self) -> None:
        """插件卸载/禁用时清理资源。"""
        logger.info("HistoriesCollectorV2 插件正在关闭...")
        if self.es_helper is not None:
            await self.es_helper.close()
        if self.download_manager is not None:
            await self.download_manager.close()
