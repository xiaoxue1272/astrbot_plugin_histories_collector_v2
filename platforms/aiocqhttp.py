"""OneBot V11 (aiocqhttp) 平台辅助类。

继承 PlatformHelper，覆写 get_chain() 使用 OneBot segment 数据增强，
覆写 get_sender() 提取昵称，覆写 _convert() 优先解析 OneBot segment。
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
    EnhancedVoice, EnhancedDownloadableComponent,
)
from data.plugins.astrbot_plugin_histories_collector_v2.platform_helper import PlatformHelper
from data.plugins.astrbot_plugin_histories_collector_v2.utils import async_retry


class AiocqhttpPlatformHelper(PlatformHelper):
    """OneBot V11 (aiocqhttp) 平台辅助类。

    覆写 get_chain() 使用 OneBot segment 数据增强，
    覆写 get_sender() 提取昵称，
    覆写 _convert() 优先解析 OneBot segment，失败回退父类。
    """

    # ── 消息链构建 ──

    async def get_chain(self) -> list[EnhancedComponent]:
        """使用 OneBot segment 数据增强构建 Enhanced 消息链。"""
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
        logger.debug(f"消息链构建完成，共 {len(result)} 个组件")
        return result

    async def _convert(
        self,
        component: BaseMessageComponent,
        ctx: object = None,
    ) -> EnhancedComponent | None:
        """优先解析 OneBot segment，失败回退父类默认转换。"""
        if isinstance(ctx, dict):
            result = await self._parse_onebot_segment(ctx)
            if result is not None:
                return result
            logger.debug(f"OneBot segment 解析失败，回退默认转换: type={ctx.get('type', '?')}")
        return await super()._convert(component, ctx)

    # ── 发送者 ──

    async def get_sender(self) -> dict:
        """从 OneBot raw 数据中提取发送者信息（含昵称）。

        OneBot sender 字段映射：
          - user_id → ES sender.id
          - nickname → ES sender.name（QQ 昵称，全局）
          - card     → ES sender.nickname（群名片/群昵称，仅群聊）
        """
        raw = self._event.message_obj.raw_message
        sender = getattr(raw, "sender", None) if raw else None
        if isinstance(sender, dict):
            return {
                "id": sender.get("user_id", ""),
                "name": sender.get("nickname", ""),
                "nickname": sender.get("card", "")
            }
        return await super().get_sender()


    # ── 转发消息解析 ──

    async def resolve_forward(self, forward_id: str, depth: int = 0) -> list[EnhancedComponent] | None:
        """通过 OneBot API get_forward_msg 展开转发消息。"""
        call_action = self._event.bot.api.call_action
        try:
            forward_data = await async_retry(
                lambda: call_action("get_forward_msg", id=forward_id),
            )
        except Exception:
            logger.info(f"转发消息 {forward_id}: 获取失败")
            return None
        if not isinstance(forward_data, dict):
            logger.info(f"转发消息 {forward_id}: 响应格式异常")
            return None

        messages_data = forward_data.get("messages", [])
        if not messages_data:
            logger.info(f"转发消息 {forward_id}: 无消息内容")
            return None

        logger.debug(f"转发消息 {forward_id} 已解析，共 {len(messages_data)} 条消息")
        nodes: list[EnhancedComponent] = []
        for msg in messages_data:
            sender = msg.get("sender", {})
            segments = msg.get("message", [])
            inner_chain = await self._onebot_segments_to_chain(segments, depth + 1)
            node = EnhancedNode(
                sender_id=str(sender.get("user_id", "")),
                sender_name=sender.get("nickname", ""),
                messages=inner_chain,
            )
            nodes.append(node)

        return nodes

    # ── OneBot segment 解析 ──

    async def _onebot_segments_to_chain(
        self,
        segments: list[dict],
        depth: int = 0,
    ) -> list[EnhancedComponent]:
        """将 OneBot V11 消息段列表转为 Enhanced 组件链。"""
        if depth > self._config.max_nesting_depth:
            logger.debug(f"已达最大嵌套深度 {self._config.max_nesting_depth}，截断")
            return []
        chain: list[EnhancedComponent] = []
        for seg in segments:
            result = await self._parse_onebot_segment(seg, depth)
            if result is not None:
                chain.append(result)
        return chain

    async def _parse_onebot_segment(self, seg: dict, depth: int = 0) -> EnhancedComponent | None:
        """按类型分发 OneBot segment 到对应解析器。"""
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
            logger.warning(f"不支持的 OneBot segment 类型: {seg_type}")
            return None
        result = handler()
        return await result if inspect.isawaitable(result) else result

    # ── OneBot segment 解析器 ──

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
        await self._download_manager.download_and_cache(comp)
        return comp

    async def _parse_record(self, data: dict, message_id: str) -> EnhancedVoice:
        if not message_id:
            message_id = self._event.message_obj.message_id
        text = await self.fetch_record_text(message_id)
        comp = EnhancedVoice(url=data.get("url", ""), text=text)
        await self._download_manager.download_and_cache(comp)
        return comp

    async def _parse_video(self, data: dict) -> EnhancedVideo:
        comp = EnhancedVideo(url=data.get("url", ""))
        await self._download_manager.download_and_cache(comp)
        return comp

    async def _parse_file(self, data: dict) -> EnhancedFile:
        comp = EnhancedFile(name=data.get("file", ""), url=data.get("url", ""))
        await self._download_manager.download_and_cache(comp)
        return comp

    async def _parse_at(self, data: dict) -> EnhancedMention | EnhancedMentionAll:
        qq = str(data.get("qq", ""))
        if qq == "all":
            return EnhancedMentionAll()
        name = (await self.get_group_member_name(qq)
                or await self.get_stranger_name(qq))
        return EnhancedMention(id=qq, name=name)

    async def _parse_reply(self, data: dict, depth: int = 0) -> EnhancedReply:
        reply_id = data.get("id", "")
        if depth >= self._config.max_nesting_depth:
            logger.debug(f"回复已达最大嵌套深度，截断: id={reply_id}")
            return EnhancedReply(id=reply_id)
        msg_data = await self.get_msg(reply_id)
        if msg_data:
            sender = msg_data.get("sender", {})
            sub_msgs = msg_data.get("message", [])
            reply_chain = await self._onebot_segments_to_chain(sub_msgs, depth + 1)
            return EnhancedReply(
                id=reply_id,
                messages=reply_chain,
                sender_id=str(sender.get("user_id", "")),
                sender_name=sender.get("nickname", ""),
                sender_nickname=sender.get("card", ""),
                time=sender.get("timestamp"),
            )
        logger.warning(f"回复 {reply_id}: get_msg 失败，仅存 id")
        return EnhancedReply(id=reply_id)

    async def _parse_forward(self, data: dict, depth: int = 0) -> EnhancedForward | EnhancedNodes:
        forward_id = str(data.get("id", ""))
        if depth >= self._config.max_nesting_depth:
            logger.debug(f"转发消息已达最大嵌套深度，截断: id={forward_id}")
            return EnhancedForward(id=forward_id)
        content = data.get("content", [])
        summary = self._parse_forward_summary() if depth == 0 else None
        if not content:
            messages = await self.resolve_forward(forward_id, depth)
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

    # ── 转发消息 XML 预览摘要 ──

    def _parse_forward_summary(self) -> str | None:
        """从 raw 消息的 XML 预览中提取转发消息摘要。"""
        raw = getattr(self._event.message_obj.raw_message, "raw", None)
        if not isinstance(raw, dict):
            return None

        elements = raw.get("elements", [])
        if not elements:
            return None

        element = elements[0]
        multi_forward_msg_element = element.get("multiForwardMsgElement", None)
        if not isinstance(multi_forward_msg_element, dict):
            return None

        xml_content = multi_forward_msg_element.get("xmlContent")
        if not xml_content:
            return None
        try:
            root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_content))
        except ET.ParseError:
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

        return " ".join(titles) if titles else None

    # ── OneBot API 辅助 ──

    async def get_msg(self, message_id: str) -> dict | None:
        """通过 OneBot API get_msg 获取完整消息数据。"""
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action("get_msg", message_id=message_id),
            )
        except Exception:
            return None
        return result if isinstance(result, dict) else None

    async def fetch_record_text(self, message_id: str) -> str | None:
        """通过 OneBot API fetch_ptt_text 获取语音转文字结果。"""
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
                logger.debug(f"语音转文字成功: {text}")
            return text
        return None

    async def get_group_member_name(self, user_id: str | None = None) -> str | None:
        """通过 get_group_member_info 获取群名片或昵称。"""
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
            return result.get("card") or result.get("nickname") or ""
        return None

    async def get_stranger_name(self, user_id: str | None = None) -> str | None:
        """通过 get_stranger_info 获取 QQ 昵称。"""
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
            return result.get("nickname") or ""
        return None
