from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from astrbot.api import logger
from astrbot.core.message.components import (
    At,
    BaseMessageComponent,
    Contact,
    Face,
    File,
    Forward,
    Image,
    Json,
    Location,
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

from data.plugins.astrbot_plugin_histories_collector_v2.file_cache import FileCache
from data.plugins.astrbot_plugin_histories_collector_v2.utils import is_http_url


class EnhancedForward(Forward):
    """Forward 子类，增加 summary 字段。"""

    summary: str | None = None

    def __init__(self, summary: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.summary = summary


class EnhancedNodes(Nodes):
    """Nodes 子类，增加 summary 字段。"""

    summary: str | None = None

    def __init__(self, summary: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.summary = summary


class EnhancedImage(Image):
    """Image 子类，增加 sub_type 和 summary 字段。

    sub_type 取值:
        0  - 普通图片
        1  - 动画表情/GIF
        7  - 表情包/热图
    """

    sub_type: int = 0
    summary: str | None = None

    def __init__(self, sub_type: int = 0, summary: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.sub_type = sub_type
        self.summary = summary


@dataclass
class ParserConfig:
    """PlatformMessageParser 的全局配置。"""

    http_session: aiohttp.ClientSession
    plugin_data_dir: Path
    max_nesting_depth: int = 3
    max_file_size_mb: int = 50


class PlatformMessageParser[E: AstrMessageEvent]:
    """平台消息解析器基类，提供默认的平台通用实现。

    负责消息链解析、summary 生成等通用逻辑。
    子类按需覆写平台差异化方法（如 QQ 的 OneBot segment 转换、Forward 展开等）。
    """

    def __init__(self, config: ParserConfig, event: E) -> None:
        self._event: E = event
        self._max_nesting_depth = config.max_nesting_depth
        self._file_cache = FileCache(
            http_session=config.http_session,
            store_dir=config.plugin_data_dir,
            max_file_size_mb=config.max_file_size_mb,
        )

    # ==================== 组件类型判断 ====================

    @staticmethod
    def _is_type_parsable(component: BaseMessageComponent) -> bool:
        return isinstance(component, (
            File, Video, Record, Image, Face,
            Node, Nodes, At, Reply,
            Plain, Share, Contact, Location, Music, Json, Forward,
        ))

    # ==================== 消息链解析 ====================

    async def _parse_single_component(
        self,
        component: BaseMessageComponent,
    ) -> dict | None:
        if not self._is_type_parsable(component):
            logger.warning(f"不支持的消息组件类型: {component.type}")
            return None

        element: dict[str, Any] = {"type": component.type.lower()}

        if isinstance(component, At):
            element["qq"] = component.qq
            element["name"] = component.name
            return element
        elif isinstance(component, Reply):
            element["id"] = component.id
            reply_chain = getattr(component, "chain", None) or []
            element["summary"] = self.build_summary(
                [c for c in reply_chain if not isinstance(c, Reply)]
            )
            return element
        elif isinstance(component, (File, Video, Image, Record)):
            url = getattr(component, "url", None) or ""
            if url and is_http_url(url):
                element["url"] = url
            path, warning = await self._file_cache.download(component)
            if path:
                element["path"] = path
            if warning:
                element["warn"] = warning
            if isinstance(component, Record):
                if component.text:
                    element["text"] = component.text
            elif isinstance(component, Image):
                element["sub_type"] = getattr(component, "sub_type", 0)
                summary = getattr(component, "summary", None)
                if summary:
                    element["summary"] = summary
            elif isinstance(component, File):
                name = getattr(component, "name", "") or ""
                if name:
                    element["name"] = name
            return element

        raw = await component.to_dict()
        data = raw.get("data", raw)
        data.pop("type", None)
        element.update(data)
        return element

    async def _parse_nested_component(
        self,
        component: BaseMessageComponent,
        depth: int,
    ) -> dict | None:
        if isinstance(component, Nodes):
            return {
                "type": component.type.lower(),
                "messages": await self.parse_message_chain(component.nodes, depth)
            }

        if isinstance(component, Node):
            return {
                "type": component.type.lower(),
                "user_id": component.uin,
                "nickname": component.name,
                "messages": await self.parse_message_chain(component.content, depth + 1),
            }

        if isinstance(component, Forward):
            resolved = await self.resolve_forward_messages(component.id)
            if resolved is None:
                logger.debug(f"转发消息 {component.id}: 当前平台不支持展开或解析失败，将以空 messages 存储")
            messages = (
                await self.parse_message_chain(resolved, depth)
                if resolved is not None
                else []
            )
            return {"type": component.type.lower(), "id": component.id, "messages": messages}

        return None

    async def parse_message_chain(
        self,
        chain: list[BaseMessageComponent],
        depth: int = 0,
    ) -> list[dict]:
        if depth > self._max_nesting_depth:
            logger.warning(f"消息链已达最大嵌套深度 {self._max_nesting_depth}，depth={depth}，已截断")
            return [{"_truncated": True, "_depth": depth}]

        elements: list[dict] = []
        for component in chain:
            try:
                element = await self._parse_nested_component(component, depth)
                if element is None:
                    element = await self._parse_single_component(component)
                if element is not None:
                    elements.append(element)
            except Exception as e:
                logger.warning(
                    f"解析消息组件失败 type={component.type}，已跳过: {e}",
                    exc_info=True,
                )
        return elements

    # ==================== 平台差异化接口 ====================

    # ---- chain / sender / group ----

    async def get_chain(self) -> list[BaseMessageComponent]:
        return self._event.get_messages()

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

    # ---- Forward ----

    async def resolve_forward_messages(self, forward_id: str) -> list[Node] | None:
        return None

    # ==================== summary 构建 ====================

    def build_summary(
        self,
        chain: list[BaseMessageComponent],
    ) -> str:
        parts: list[str] = []
        for comp in chain:
            if isinstance(comp, Plain):
                parts.append(comp.text)
            elif isinstance(comp, Image):
                summary = getattr(comp, "summary", "")
                if summary:
                    parts.append(summary if summary.startswith("[") and summary.endswith("]") else f"[{summary}]")
                else:
                    parts.append("[图片]")
            elif isinstance(comp, Face):
                parts.append(f"[表情:{comp.id}]")
            elif isinstance(comp, At):
                parts.append(f"[@:{comp.name}]")
            elif isinstance(comp, Reply):
                reply_summary = self.build_summary(
                    [c for c in getattr(comp, "chain", []) if not isinstance(c, Reply)]
                )
                if reply_summary:
                    parts.append(f"[引用消息:({comp.sender_nickname}:{reply_summary})]")
                else:
                    parts.append("[引用消息]")
            elif isinstance(comp, Record):
                if comp.text:
                    parts.append(f"[语音:({comp.text})]")
                else:
                    parts.append("[语音]")
            elif isinstance(comp, Video):
                parts.append("[视频]")
            elif isinstance(comp, File):
                parts.append("[文件]")
            elif isinstance(comp, Json):
                parts.append("[JSON]")
            elif isinstance(comp, (Forward, Nodes)):
                summary = getattr(comp, "summary", "")
                if summary:
                    parts.append(f"[聊天记录:{summary}]")
                else:
                    parts.append("[聊天记录]")
            else:
                parts.append(f"[{comp.type}]")
        return " ".join(parts).strip()
