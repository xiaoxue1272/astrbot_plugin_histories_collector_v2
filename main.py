import json

from snowflake import SnowflakeGenerator

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig

from astrbot.api import logger
from astrbot.core.star.filter.event_message_type import EventMessageType
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterType
from data.plugins.astrbot_plugin_histories_collector_v2.config import (
    HistoriesCollectorConfig,
)
from data.plugins.astrbot_plugin_histories_collector_v2.es_helper import ESHelper
from data.plugins.astrbot_plugin_histories_collector_v2.group_filter import GroupFilter
from data.plugins.astrbot_plugin_histories_collector_v2.enhanced import build_summary
from data.plugins.astrbot_plugin_histories_collector_v2.platform_helper import (
    CollectorConfig,
    create_platform_helper,
)
from data.plugins.astrbot_plugin_histories_collector_v2.utils import PLUGIN_NAME

def _inject_group_filter(body: dict, event: AstrMessageEvent) -> None:
    """Auto-scope query to current group when triggered from a group message."""
    group_id: str | None = None
    try:
        group_id = event.get_group_id()
    except (AttributeError, TypeError):
        return
    if not group_id:
        return
    group_filter = {"nested": {"path": "group", "query": {"term": {"group.id": group_id}}}}
    if "query" not in body:
        body["query"] = group_filter
    elif "bool" in body["query"]:
        body["query"]["bool"].setdefault("filter", []).append(group_filter)
    else:
        body["query"] = {"bool": {"must": [body["query"]], "filter": [group_filter]}}


@register(
    PLUGIN_NAME,
    "xiaoxue1272",
    "Astrbot 全平台群消息收集器V2(ES版)",
    "v0.1.0",
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

    @filter.llm_tool(name="search_es")
    async def search_es(self, event: AstrMessageEvent, body: dict) -> str:
        """查询群聊历史消息记录。body 为 ES 原生搜索 body，可按需包含 query/sort/aggs/size/from/_source 等字段。

        Args:
            body(object): 标准 ES _search 请求 body，所有字段直接透传给 ES。索引固定为 message-histories-v2。群聊自动限定当前群。
        """
        if not self.es_helper or not self.es_helper.is_connected:
            return json.dumps({"error": "ES 未连接"}, ensure_ascii=False)

        body = body or {}
        _inject_group_filter(body, event)

        try:
            resp = await self.es_helper.search(body)
        except Exception as e:
            return json.dumps({"error": f"ES 查询失败: {e}"}, ensure_ascii=False)
        return json.dumps(resp, ensure_ascii=False, default=str)

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = HistoriesCollectorConfig(config)
        self.id_generator = SnowflakeGenerator(instance=0)

    async def initialize(self) -> None:
        """连接 Elasticsearch 并初始化索引。"""
        logger.info("HistoriesCollectorV2 插件正在初始化...")

        self.collector_config = CollectorConfig(
            max_nesting_depth=self.config.max_nesting_depth,
            max_file_size_mb=self.config.max_file_size_mb,
        )

        self.group_filter = GroupFilter(self.config.group_filter)
        self.es_helper = ESHelper(self.config.es_config)
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

        try:
            await self.es_helper.save_message(next(self.id_generator), doc)
        except Exception as e:
            logger.error(f"ES 保存消息失败，消息已丢弃: {e}")

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

        helper = create_platform_helper(event, self.collector_config)

        group_doc = await helper.get_group()
        sender_doc = await helper.get_sender()
        chain = await helper.get_chain()

        # Skip empty chains (system notifications, unparseable messages)
        if not chain:
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
        if self.es_helper:
            await self.es_helper.close()