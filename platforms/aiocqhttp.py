"""OneBot V11 (aiocqhttp) platform helper.

Inherits PlatformHelper, overrides get_chain() with OneBot segment augmentation,
get_sender() with nickname extraction, and resolve_forward() via OneBot API.
"""

import inspect
import re
import xml.etree.ElementTree as ET

from astrbot.core.message.components import BaseMessageComponent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from astrbot.api import logger
from data.plugins.astrbot_plugin_histories_collector_v2.chain_iter import MessageChainIter
from data.plugins.astrbot_plugin_histories_collector_v2.enhanced import (
    EnhancedComponent,
    EnhancedFace,
    EnhancedFile,
    EnhancedForward,
    EnhancedImage,
    EnhancedJson,
    EnhancedMention,
    EnhancedMentionAll,
    EnhancedNode,
    EnhancedNodes,
    EnhancedPlain,
    EnhancedReply,
    EnhancedSticker,
    EnhancedVideo,
    EnhancedVoice,
)
from data.plugins.astrbot_plugin_histories_collector_v2.platform_helper import PlatformHelper
from data.plugins.astrbot_plugin_histories_collector_v2.utils import async_retry, is_http_url


class AiocqhttpPlatformHelper(PlatformHelper):
    """OneBot V11 (aiocqhttp) platform helper.

    Overrides get_chain() with OneBot segment data augmentation,
    get_sender() with nickname extraction, and resolve_forward()
    via OneBot API get_forward_msg.
    """

    # ── Chain building ──

    async def get_chain(self) -> list[EnhancedComponent]:
        """Build the Enhanced chain with OneBot segment data augmentation."""
        raw = self._event.message_obj.raw_message
        segments = getattr(raw, "message", []) if raw else []
        chain = self._event.get_messages()
        if len(chain) != len(segments):
            segments = None
        result: list[EnhancedComponent] = []
        for comp, ctx in MessageChainIter(chain, segments):
            enhanced = await self._convert(comp, ctx)
            if enhanced is not None:
                result.append(enhanced)
        return result

    async def _convert(
        self,
        component: BaseMessageComponent,
        ctx: object = None,
    ) -> EnhancedComponent | None:
        """OneBot segment first, fallback to parent default conversion."""
        if isinstance(ctx, dict):
            result = await self._parse_onebot_segment(ctx)
            if result is not None:
                return result
        return await super()._convert(component, ctx)

    # ── Sender ──

    async def get_sender(self) -> dict:
        """Sender info including nickname from OneBot raw data."""
        sender_doc = {
            "id": self._event.get_sender_id(),
            "name": self._event.get_sender_name(),
        }
        raw = self._event.message_obj.raw_message
        raw_sender = getattr(raw, "sender", None) if raw else None
        if isinstance(raw_sender, dict):
            nickname = raw_sender.get("card")
            if nickname:
                sender_doc["nickname"] = nickname
        return sender_doc

    # ── Forward resolution ──

    async def resolve_forward(self, forward_id: str) -> list[EnhancedComponent] | None:
        """Expand forward messages via OneBot API get_forward_msg."""
        call_action = self._event.bot.api.call_action
        try:
            forward_data = await async_retry(
                lambda: call_action("get_forward_msg", id=forward_id),
            )
        except Exception:
            logger.warning(f"Forward message {forward_id}: fetch failed")
            return None
        if not isinstance(forward_data, dict):
            logger.warning(f"Forward message {forward_id}: invalid response")
            return None

        messages_data = forward_data.get("messages", [])
        if not messages_data:
            logger.warning(f"Forward message {forward_id}: no message content")
            return None

        logger.debug(f"Forward message {forward_id} resolved, {len(messages_data)} messages")
        nodes: list[EnhancedComponent] = []
        for msg in messages_data:
            sender = msg.get("sender", {})
            segments = msg.get("message", [])
            inner_chain = await self._onebot_segments_to_chain(segments)
            node = EnhancedNode(
                sender_id=str(sender.get("user_id", "")),
                sender_name=sender.get("nickname", ""),
                messages=inner_chain,
            )
            nodes.append(node)

        return nodes

    # ── OneBot segment parsing ──

    async def _onebot_segments_to_chain(
        self,
        segments: list[dict],
        depth: int = 0,
    ) -> list[EnhancedComponent]:
        """Convert OneBot V11 message segments to Enhanced component chain."""
        if depth > self._config.max_nesting_depth:
            return []
        chain: list[EnhancedComponent] = []
        for seg in segments:
            result = await self._parse_onebot_segment(seg, depth)
            if result is not None:
                chain.append(result)
        return chain

    async def _parse_onebot_segment(self, seg: dict, depth: int = 0) -> EnhancedComponent | None:
        """Dispatch OneBot segment by type to the corresponding parser."""
        seg_type = seg.get("type", "")
        seg_data = seg.get("data", {})
        if depth == 0:
            message_id = self._event.message_obj.message_id
        else:
            message_id = seg.get("message_id", "")
        handlers = {
            "text": lambda: self._parse_text(seg_data),
            "image": lambda: self._parse_image(seg_data),
            "record": lambda: self._parse_record(seg_data, message_id),
            "video": lambda: self._parse_video(seg_data),
            "file": lambda: self._parse_file(seg_data),
            "at": lambda: self._parse_at(seg_data),
            "reply": lambda: self._parse_reply(seg_data, depth),
            "forward": lambda: self._parse_forward(seg_data, depth),
            "node": lambda: self._parse_node(seg_data, depth),
            "json": lambda: self._parse_json(seg_data),
            "face": lambda: self._parse_face(seg_data),
        }

        handler = handlers.get(seg_type)
        if handler is None:
            logger.warning(f"Unsupported OneBot segment type: {seg_type}")
            return None
        result = handler()
        return await result if inspect.isawaitable(result) else result

    # ── OneBot segment parsers ──

    @staticmethod
    def _parse_text(data: dict) -> EnhancedPlain:
        return EnhancedPlain(text=str(data.get("text", "")))

    async def _parse_image(self, data: dict) -> EnhancedImage | EnhancedSticker:
        sub_type = int(data.get("sub_type", 0))
        url = data.get("url", "")
        summary = data.get("summary") or None
        if sub_type != 0:
            comp: EnhancedSticker = EnhancedSticker(url=url, summary=summary)
        else:
            comp = EnhancedImage(url=url)
        await self._download_media(comp)
        return comp

    async def _parse_record(self, data: dict, message_id: str) -> EnhancedVoice:
        if not message_id:
            message_id = self._event.message_obj.message_id
        text = await self.fetch_record_text(message_id)
        comp = EnhancedVoice(url=data.get("url", ""), text=text)
        await self._download_media(comp)
        return comp

    async def _parse_video(self, data: dict) -> EnhancedVideo:
        comp = EnhancedVideo(url=data.get("url", ""))
        await self._download_media(comp)
        return comp

    async def _parse_file(self, data: dict) -> EnhancedFile:
        comp = EnhancedFile(name=data.get("file", ""), url=data.get("url", ""))
        await self._download_media(comp)
        return comp

    async def _download_media(
        self,
        comp: EnhancedImage | EnhancedSticker | EnhancedVideo | EnhancedVoice | EnhancedFile,
    ) -> None:
        url = getattr(comp, "url", "") or ""
        if not url:
            return
        file_name = getattr(comp, "name", "") or ""
        cached_path, warning = await self._file_manager.download(
            url, comp.type, file_name=file_name,
        )
        if cached_path:
            comp.path = cached_path
        if warning:
            comp.warn = warning

    async def _parse_at(self, data: dict) -> EnhancedMention | EnhancedMentionAll:
        qq = str(data.get("qq", ""))
        if qq == "all":
            return EnhancedMentionAll()
        name = (await self.get_group_member_name(qq)
                or await self.get_stranger_name(qq))
        logger.debug(f"Parsed @: qq={qq}, name={name}")
        return EnhancedMention(id=qq, name=name)

    async def _parse_reply(self, data: dict, depth: int = 0) -> EnhancedReply:
        reply_id = str(data.get("id", ""))
        logger.debug(f"Parsing reply: id={reply_id}")
        msg_data = await self.get_msg(reply_id)
        if msg_data:
            sender = msg_data.get("sender", {})
            sub_msgs = msg_data.get("message", [])
            reply_chain = await self._onebot_segments_to_chain(sub_msgs, depth + 1)
            logger.debug(f"Reply {reply_id}: sender={sender.get('nickname')}, chain_len={len(reply_chain)}")
            return EnhancedReply(
                id=reply_id,
                messages=reply_chain,
                sender_id=str(sender.get("user_id", "")),
                sender_name=sender.get("nickname", ""),
                sender_nickname=sender.get("card", ""),
                time=sender.get("timestamp"),
            )
        logger.warning(f"Reply {reply_id}: get_msg failed, storing id only")
        return EnhancedReply(id=reply_id)

    async def _parse_forward(self, data: dict, depth: int = 0) -> EnhancedForward | EnhancedNodes:
        forward_id = str(data.get("id", ""))
        if depth >= self._config.max_nesting_depth:
            return EnhancedForward(id=forward_id)
        content = data.get("content", [])
        summary = self._parse_forward_summary(forward_id) if depth == 0 else None
        if not content:
            logger.debug(f"Parsed forward: id={forward_id}, summary={summary}")
            messages = await self.resolve_forward(forward_id)
            return EnhancedForward(id=forward_id, summary=summary, messages=messages)
        node_list: list[EnhancedComponent] = []
        for node_data in content:
            inner_segments = node_data.get("message", [])
            inner_chain = await self._onebot_segments_to_chain(inner_segments, depth + 1)
            sender = node_data.get("sender", {})
            node_list.append(EnhancedNode(
                sender_id=str(sender.get("user_id", "")),
                sender_name=sender.get("nickname", ""),
                messages=inner_chain,
            ))
        logger.debug(f"Parsed forward (embedded): id={forward_id}, nodes={len(node_list)}, summary={summary}")
        return EnhancedNodes(messages=node_list, summary=summary)

    async def _parse_node(self, data: dict, depth: int = 0) -> EnhancedNode:
        inner_chain = await self._onebot_segments_to_chain(data.get("content", []), depth + 1)
        return EnhancedNode(
            sender_id=str(data.get("uin", "")),
            sender_name=data.get("name", ""),
            messages=inner_chain,
        )

    @staticmethod
    def _parse_json(data: dict) -> EnhancedJson:
        return EnhancedJson(data=str(data))

    @staticmethod
    def _parse_face(data: dict) -> EnhancedFace:
        return EnhancedFace(id=str(data.get("id", "")))

    # ── Forward summary from XML preview ──

    def _parse_forward_summary(self, forward_id: str) -> str | None:
        """Extract forward summary from the raw message XML preview."""
        raw = getattr(self._event.message_obj.raw_message, "raw", None)
        if not isinstance(raw, dict):
            logger.debug("Parse forward summary: raw is not dict")
            return None

        elements = raw.get("elements", [])
        if not elements:
            logger.debug("Parse forward summary: elements empty")
            return None

        element = elements[0]
        multi_forward_msg_element = element.get("multiForwardMsgElement", None)
        if not isinstance(multi_forward_msg_element, dict):
            logger.debug("Parse forward summary: multiForwardMsgElement is not dict")
            return None

        xml_content = multi_forward_msg_element.get("xmlContent")
        if not xml_content:
            logger.debug("Parse forward summary: xmlContent empty")
            return None
        try:
            root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_content))
        except ET.ParseError as e:
            logger.debug(f"Forward XML parse failed: {e}")
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
            logger.debug(f"Forward summary parsed: {len(titles)} items")
            return " ".join(titles)

        logger.debug("Parse forward summary: no content")
        return None

    # ── OneBot API helpers ──

    async def get_msg(self, message_id: str) -> dict | None:
        """Fetch full message data via OneBot API get_msg."""
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action("get_msg", message_id=message_id),
            )
        except Exception:
            return None
        return result if isinstance(result, dict) else None

    async def fetch_record_text(self, message_id: str) -> str | None:
        """Fetch voice-to-text result via OneBot API fetch_ptt_text."""
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action("fetch_ptt_text", message_id=message_id),
            )
        except Exception:
            return None
        if isinstance(result, dict):
            text = result.get("text")
            if text:
                logger.debug(f"Voice-to-text success: {text}")
            return text
        return None

    async def get_group_member_name(self, user_id: str | None = None) -> str | None:
        """Fetch group card or nickname via get_group_member_info."""
        if user_id is None:
            user_id = self._event.get_sender_id()
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action(
                    "get_group_member_info",
                    group_id=self._event.get_group_id(),
                    user_id=user_id,
                ),
            )
        except Exception:
            return None
        if isinstance(result, dict):
            name = result.get("card") or result.get("nickname") or ""
            logger.debug(f"get_group_member_info: user_id={user_id}, name={name}")
            return name
        return None

    async def get_stranger_name(self, user_id: str | None = None) -> str | None:
        """Fetch QQ nickname via get_stranger_info."""
        if user_id is None:
            user_id = self._event.get_sender_id()
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action("get_stranger_info", user_id=user_id),
            )
        except Exception:
            return None
        if isinstance(result, dict):
            name = result.get("nickname") or ""
            logger.debug(f"get_stranger_info: user_id={user_id}, name={name}")
            return name
        return None
