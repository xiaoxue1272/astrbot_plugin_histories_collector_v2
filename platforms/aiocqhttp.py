import asyncio
import inspect
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable

from astrbot.core.message.components import (
    At,
    BaseMessageComponent,
    Face,
    File,
    Forward,
    Image,
    Json,
    Node,
    Nodes,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from astrbot.api import logger
from data.plugins.astrbot_plugin_histories_collector_v2.platforms.base import (
    PlatformMessageParser,
    EnhancedForward,
    EnhancedNodes
)


class AiocqhttpMessageParser(PlatformMessageParser[AiocqhttpMessageEvent]):
    """QQ (aiocqhttp / OneBot V11) 平台消息解析器。"""

    # ---- chain 构建 ----

    async def get_chain(self) -> list[BaseMessageComponent]:
        raw = self._event.message_obj.raw_message
        segments = getattr(raw, "message", []) if raw else []
        chain = self._event.get_messages()
        if segments and len(segments) == len(chain):
            logger.debug(f"增强 chain: segments 数量={len(segments)}, chain 数量={len(chain)}")
            for i, comp in enumerate(chain):
                if not isinstance(comp, (Plain, At, Reply, Json, Face)):
                    logger.debug(f"替换 chain[{i}]: 框架类型={type(comp).__name__}, OneBot类型={segments[i].get('type')}")
                    new_comp = await self._parse_onebot_segment(segments[i])
                    if new_comp is not None:
                        chain[i] = new_comp
        return chain

    async def _onebot_segments_to_chain(
        self,
        segments: list[dict],
    ) -> list[BaseMessageComponent]:
        """将 OneBot V11 消息段转为 BaseMessageComponent 链。"""
        chain: list[BaseMessageComponent] = []
        for seg in segments:
            result = await self._parse_onebot_segment(seg)
            if result is not None:
                chain.append(result)
        return chain

    @staticmethod
    async def _retry(
        action: Callable[[], Awaitable[Any]],
        action_name: str,
        max_retries: int = 3,
        delay: float = 5.0,
    ) -> Any | None:
        """带重试的异步调用封装。

        Args:
            action: 异步可调用对象。
            action_name: 操作名称（用于日志）。
            max_retries: 最大重试次数。
            delay: 重试间隔（秒）。

        Returns:
            成功时返回结果，全部失败返回 None。
        """
        for attempt in range(max_retries):
            try:
                return await action()
            except Exception as e:
                logger.debug(f"{action_name} 失败(尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
        logger.debug(f"{action_name}: {max_retries} 次重试均失败")
        return None

    async def _parse_onebot_segment(
        self,
        seg: dict,
    ) -> BaseMessageComponent | None:
        seg_type = seg.get("type", "")
        seg_data = seg.get("data", {})

        handlers = {
            "text": lambda: self._parse_text(seg_data),
            "image": lambda: self._parse_image(seg_data),
            "record": lambda: self._parse_record(seg_data),
            "video": lambda: self._parse_video(seg_data),
            "file": lambda: self._parse_file(seg_data),
            "at": lambda: self._parse_at(seg_data),
            "reply": lambda: self._parse_reply(seg_data),
            "forward": lambda: self._parse_forward(seg_data),
            "node": lambda: self._parse_node(seg_data),
            "json": lambda: self._parse_json(seg_data),
            "face": lambda: self._parse_face(seg_data),
        }

        handler = handlers.get(seg_type)
        if handler is None:
            logger.warning(f"未知的 OneBot 消息段类型: {seg_type}")
            return None
        result = handler()
        return await result if inspect.isawaitable(result) else result

    @staticmethod
    def _parse_text(data: dict) -> Plain:
        return Plain(text=str(data.get("text", "")))

    @staticmethod
    def _parse_image(data: dict) -> Image:
        return Image(url=data.get("url", ""), file=data.get("file", ""))

    async def _parse_record(self, data: dict) -> Record:
        return Record(
            url=data.get("url", ""),
            file=data.get("file", ""),
            text=await self.fetch_record_text(),
        )

    @staticmethod
    def _parse_video(data: dict) -> Video:
        return Video(url=data.get("url", ""), file=data.get("file", ""))

    @staticmethod
    def _parse_file(data: dict) -> File:
        return File(name=data.get("name", ""), url=data.get("url", ""), file=data.get("file", ""))

    async def _parse_at(self, data: dict) -> At:
        qq = str(data.get("qq", ""))
        name = (await self.get_group_member_name(qq)
                or await self.get_stranger_name(qq))
        logger.debug(f"解析 @: qq={qq}, name={name}")
        return At(qq=qq, name=name)

    async def _parse_reply(self, data: dict) -> Reply:
        reply_id = str(data.get("id", ""))
        logger.debug(f"解析 reply: id={reply_id}")
        msg_data = await self.get_msg(reply_id)
        if msg_data:
            sender = msg_data.get("sender", {})
            sub_msgs = msg_data.get("message", [])
            sub_msgs = [m for m in sub_msgs if m.get("type") != "reply"]
            reply_chain = await self._onebot_segments_to_chain(sub_msgs)
            logger.debug(f"reply {reply_id}: sender={sender.get('nickname')}, chain 长度={len(reply_chain)}")
            return Reply(
                id=reply_id,
                chain=reply_chain,
                sender_id=sender.get("user_id"),
                sender_nickname=sender.get("nickname"),
                time=sender.get("timestamp"),
                message_str=self.build_summary(reply_chain),
            )
        logger.warning(f"reply {reply_id}: get_msg 失败，仅存 id")
        return Reply(id=reply_id)

    async def _parse_forward(self, data: dict) -> Forward | Nodes:
        content = data.get("content", [])
        forward_id = str(data.get("id", ""))
        summary = self._parse_forward_summary(forward_id)
        if not content:
            logger.debug(f"解析 forward: id={forward_id}, summary={summary}")
            return EnhancedForward(id=forward_id, summary=summary)
        node_list: list[Node] = []
        for node_data in content:
            inner_segments = node_data.get("message", [])
            inner_chain = await self._onebot_segments_to_chain(inner_segments)
            sender = node_data.get("sender", {})
            node_list.append(Node(
                uin=sender.get("user_id"),
                name=sender.get("nickname"),
                content=inner_chain,
            ))
        logger.debug(f"解析 forward(内嵌): id={forward_id}, 节点数={len(node_list)}, summary={summary}")
        return EnhancedNodes(nodes=node_list, summary=summary)

    async def _parse_node(self, data: dict) -> Node:
        inner_chain = await self._onebot_segments_to_chain(data.get("content", []))
        return Node(
            uin=data.get("uin"),
            name=data.get("name"),
            content=inner_chain,
        )

    @staticmethod
    def _parse_json(data: dict) -> Json:
        return Json(data=data)

    @staticmethod
    def _parse_face(data: dict) -> Face:
        return Face(id=str(data.get("id", "")))

    def _parse_forward_summary(self, forward_id: str) -> str | None:
        """从 raw 消息的 XML 预览中解析 Forward 摘要。"""
        raw = getattr(self._event.message_obj.raw_message, "raw", None)
        if not isinstance(raw, dict):
            logger.debug("解析 forward summary: raw 不是 dict")
            return None

        elements = raw.get("elements", [])
        if not elements:
            logger.debug("解析 forward summary: elements 为空")
            return None

        element = elements[0]
        multi_forward_msg_element = element.get("multiForwardMsgElement", None)
        if not isinstance(multi_forward_msg_element, dict):
            logger.debug("解析 forward summary: multiForwardMsgElement 不是 dict")
            return None

        xml_content = multi_forward_msg_element.get("xmlContent")
        if not xml_content:
            logger.debug("解析 forward summary: xmlContent 为空")
            return None
        try:
            root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_content))
        except ET.ParseError as e:
            logger.debug(f"Forward XML 解析失败: {e}")
            return None

        titles: list[str] = []
        for title_elem in root.iter("title"):
            text = (title_elem.text or "").strip()
            if text:
                titles.append(f"({text})")
        for summary_elem in root.iter("summary"):
            text = (summary_elem.text or "").strip()
            if text:
                titles.append(f"({text})")

        if titles:
            logger.debug(f"解析 forward summary 成功: {len(titles)} 条")
            return " ".join(titles)

        logger.debug("解析 forward summary: 无内容")
        return None
    # ---- sender ----

    async def get_sender(self) -> dict:
        sender_doc = await super().get_sender()
        raw = self._event.message_obj.raw_message
        raw_sender = getattr(raw, "sender", None) if raw else None
        if isinstance(raw_sender, dict):
            nickname = raw_sender.get("nickname")
            if nickname:
                sender_doc["nickname"] = nickname
        return sender_doc

    # ---- Forward 能力 ----

    async def resolve_forward_messages(self, forward_id: str) -> list[Node] | None:
        if not isinstance(self._event, AiocqhttpMessageEvent):
            return None

        call_action = self._event.bot.api.call_action
        forward_data = await self._retry(
            lambda: call_action("get_forward_msg", id=forward_id),
            f"get_forward_msg({forward_id})",
        )
        if not isinstance(forward_data, dict):
            logger.warning(f"转发消息 {forward_id}: 获取失败或响应异常")
            return None

        messages_data = forward_data.get("messages", [])
        if not messages_data:
            logger.warning(f"转发消息 {forward_id}: 已解析但无消息内容")
            return None

        logger.debug(f"转发消息 {forward_id} 已解析，共 {len(messages_data)} 条")
        nodes: list[Node] = []
        for msg in messages_data:
            sender = msg.get("sender", {})
            segments = msg.get("message", [])
            chain = await self._onebot_segments_to_chain(segments)
            node = Node(
                uin=sender.get("user_id"),
                name=sender.get("nickname"),
                content=chain,
            )
            nodes.append(node)

        return nodes

    # ---- 消息查询 ----

    async def get_msg(self, message_id: str) -> dict | None:
        """通过 OneBot API 获取指定消息的完整数据。"""
        if not isinstance(self._event, AiocqhttpMessageEvent):
            return None

        call_action = self._event.bot.api.call_action
        result = await self._retry(
            lambda: call_action("get_msg", message_id=message_id),
            f"get_msg({message_id})",
        )
        return result if isinstance(result, dict) else None

    @staticmethod
    def _build_message_str(chain: list[BaseMessageComponent]) -> str:
        """从消息链构建纯文本 message_str，与框架行为一致。

        只提取 Plain.text 和 At 的昵称/QQ，忽略图片、表情等非文本组件。
        """
        parts: list[str] = []
        for comp in chain:
            if isinstance(comp, Plain):
                parts.append(comp.text)
            elif isinstance(comp, At):
                parts.append(f" @{comp.name or comp.qq} ")
        return "".join(parts)


    async def fetch_record_text(self) -> str | None:
        if not isinstance(self._event, AiocqhttpMessageEvent):
            return None

        call_action = self._event.bot.api.call_action
        message_id = self._event.message_obj.message_id
        result = await self._retry(
            lambda: call_action("fetch_ptt_text", message_id=message_id),
            f"fetch_ptt_text({message_id})",
        )
        if isinstance(result, dict):
            text = result.get("text")
            if text:
                logger.debug(f"语音转文字成功: {text}")
            return text
        return None

    async def get_group_member_name(self, user_id: str | None = None) -> str | None:
        """通过 get_group_member_info 获取群名片或群昵称。"""
        if user_id is None:
            user_id = self._event.get_sender_id()
        if not isinstance(self._event, AiocqhttpMessageEvent):
            return None
        call_action = self._event.bot.api.call_action
        result = await self._retry(
            lambda: call_action("get_group_member_info", group_id=self._event.get_group_id(), user_id=user_id),
            f"get_group_member_info({user_id})",
        )
        if isinstance(result, dict):
            name = result.get("card") or result.get("nickname") or ""
            logger.debug(f"get_group_member_info: user_id={user_id}, name={name}")
            return name
        return None

    async def get_stranger_name(self, user_id: str | None = None) -> str | None:
        """通过 get_stranger_info 获取 QQ 昵称。"""
        if user_id is None:
            user_id = self._event.get_sender_id()
        if not isinstance(self._event, AiocqhttpMessageEvent):
            return None
        call_action = self._event.bot.api.call_action
        result = await self._retry(
            lambda: call_action("get_stranger_info", user_id=user_id),
            f"get_stranger_info({user_id})",
        )
        if isinstance(result, dict):
            name = result.get("nickname") or ""
            logger.debug(f"get_stranger_info: user_id={user_id}, name={name}")
            return name
        return None