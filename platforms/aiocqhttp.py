"""OneBot V11 (aiocqhttp) 平台辅助类。

继承 PlatformHelper，覆写 get_chain() 使用 OneBot segment 数据增强，
覆写 get_sender() 提取昵称，覆写 _convert() 优先解析 OneBot segment。
"""

import json
import re
import xml.etree.ElementTree as ET

from astrbot.api import logger
from data.plugins.astrbot_plugin_histories_collector_v2.chain_iter import (
    MessageChainIter,
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
    EnhancedNode,
    EnhancedNodes,
    EnhancedPlain,
    EnhancedReply,
    EnhancedSticker,
    EnhancedVideo,
    EnhancedVoice,
)
from data.plugins.astrbot_plugin_histories_collector_v2.platform_helper import (
    PlatformHelper,
)
from data.plugins.astrbot_plugin_histories_collector_v2.utils import async_retry


class AiocqhttpPlatformHelper(PlatformHelper):
    """OneBot V11 (aiocqhttp) 平台辅助类。

    覆写 _build_chain() 使用 OneBot segment 数据增强，
    覆写 get_sender() 提取昵称，
    覆写 _convert() 优先解析 OneBot segment，失败回退父类。
    解析类型过滤由基类 get_chain() 统一处理。
    """

    # ── 消息链构建 ──

    async def _build_chain(self) -> list[EnhancedComponent]:
        """使用 OneBot segment 数据增强构建原始 Enhanced 消息链。"""
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

    # ── 各类型组件转换（有 OneBot segment 数据时优先用它，否则回退父类） ──
    #
    # 每个类型只有一个方法：ctx 是 OneBot segment dict 时用段数据解析
    # （嵌套展开路径会传 component=None），否则回退父类的框架组件转换。
    # depth 仅 reply/forward/node 使用，由 _parse_onebot_segment 传入。

    async def _convert_plain(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            return EnhancedPlain(text=str(ctx.get("data", {}).get("text", "")))
        return await super()._convert_plain(component, ctx)

    async def _convert_image(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            try:
                sub_type = int(data.get("sub_type") or 0)
            except (TypeError, ValueError):
                logger.warning(
                    f"图片 sub_type 异常，按普通图片处理: {data.get('sub_type')!r}"
                )
                sub_type = 0
            url = data.get("url", "")
            name = data.get("file", "")
            if sub_type != 0:
                return EnhancedSticker(
                    url=url, name=name, summary=data.get("summary") or None
                )
            return EnhancedImage(url=url, name=name)
        return await super()._convert_image(component, ctx)

    async def _convert_record(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            message_id = ctx.get("message_id") or self._event.message_obj.message_id
            text = await self.fetch_record_text(message_id)
            return EnhancedVoice(
                url=data.get("url", ""), name=data.get("file", ""), text=text
            )
        return await super()._convert_record(component, ctx)

    async def _convert_video(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            return EnhancedVideo(url=data.get("url", ""), name=data.get("file", ""))
        return await super()._convert_video(component, ctx)

    async def _convert_file(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            return EnhancedFile(name=data.get("file", ""), url=data.get("url", ""))
        return await super()._convert_file(component, ctx)

    async def _convert_at(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            qq = str(data.get("qq", ""))
            if qq == "all":
                return EnhancedMentionAll()

            # OneBot API 返回 dict，必须用 .get() 取值；getattr 对 dict 无效
            name, nickname = "", ""
            group_member = await self.get_group_member(qq)
            if isinstance(group_member, dict):
                name = str(group_member.get("nickname") or "")
                nickname = str(group_member.get("card") or "")
            else:
                stranger = await self.get_stranger(qq)
                if isinstance(stranger, dict):
                    name = str(stranger.get("nickname") or "")
            return EnhancedMention(id=qq, name=name, nickname=nickname)
        return await super()._convert_at(component, ctx)

    async def _convert_reply(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            reply_id = ctx.get("data", {}).get("id", "")
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
        return await super()._convert_reply(component, ctx)

    async def _convert_forward(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            forward_id = str(data.get("id", ""))
            if depth >= self._config.max_nesting_depth:
                logger.debug(f"转发消息已达最大嵌套深度，截断: id={forward_id}")
                return EnhancedForward(id=forward_id)
            content = data.get("content", [])
            if not isinstance(content, list):
                logger.warning(f"转发消息 {forward_id}: content 格式异常，改为接口展开")
                content = []
            summary = self._parse_forward_summary() if depth == 0 else None
            if not content:
                messages = await self.resolve_forward(forward_id, depth)
                return EnhancedForward(
                    id=forward_id, summary=summary, messages=messages
                )
            node_list: list[EnhancedComponent] = []
            for node_data in content:
                if not isinstance(node_data, dict):
                    logger.warning(f"转发消息 {forward_id}: 存在非法节点，已跳过")
                    continue
                inner_chain = await self._onebot_segments_to_chain(
                    node_data.get("message", []), depth + 1
                )
                sender = node_data.get("sender", {})
                if not isinstance(sender, dict):
                    sender = {}
                node_list.append(
                    EnhancedNode(
                        sender_id=str(sender.get("user_id", "")),
                        sender_name=sender.get("nickname", ""),
                        messages=inner_chain,
                    )
                )
            return EnhancedNodes(messages=node_list, summary=summary)
        return await super()._convert_forward(component, ctx)

    async def _convert_node(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            data = ctx.get("data", {})
            inner_chain = await self._onebot_segments_to_chain(
                data.get("content", []), depth + 1
            )
            return EnhancedNode(
                sender_id=str(data.get("uin", "")),
                sender_name=data.get("name", ""),
                messages=inner_chain,
            )
        return await super()._convert_node(component, ctx)

    async def _convert_json(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            return EnhancedJson(
                data=json.dumps(ctx.get("data", {}), ensure_ascii=False)
            )
        return await super()._convert_json(component, ctx)

    async def _convert_face(self, component, ctx=None, depth=0):
        if isinstance(ctx, dict):
            return EnhancedFace(id=str(ctx.get("data", {}).get("id", "")))
        return await super()._convert_face(component, ctx)

    # ── OneBot segment 解析（嵌套展开路径） ──

    async def _onebot_segments_to_chain(
        self,
        segments: list[dict],
        depth: int = 0,
    ) -> list[EnhancedComponent]:
        """将 OneBot V11 消息段列表转为 Enhanced 组件链。"""
        if depth > self._config.max_nesting_depth:
            logger.debug(f"已达最大嵌套深度 {self._config.max_nesting_depth}，截断")
            return []
        if not isinstance(segments, list):
            logger.warning(
                f"OneBot 消息段列表格式异常: {type(segments).__name__}，按空链处理"
            )
            return []
        chain: list[EnhancedComponent] = []
        for seg in segments:
            if not isinstance(seg, dict):
                logger.warning(f"跳过非法的 OneBot 消息段: {type(seg).__name__}")
                continue
            result = await self._parse_onebot_segment(seg, depth)
            if result is not None:
                chain.append(result)
        return chain

    async def _parse_onebot_segment(
        self, seg: dict, depth: int = 0
    ) -> EnhancedComponent | None:
        """按段类型分发到对应的组件转换方法（嵌套展开路径使用）。

        Args:
            seg: OneBot 消息段 dict。
            depth: 当前嵌套深度。

        Returns:
            Enhanced 组件；不支持的段类型返回 None。
        """
        dispatch = {
            "text": self._convert_plain,
            "image": self._convert_image,
            "record": self._convert_record,
            "video": self._convert_video,
            "file": self._convert_file,
            "at": self._convert_at,
            "reply": self._convert_reply,
            "forward": self._convert_forward,
            "node": self._convert_node,
            "json": self._convert_json,
            "face": self._convert_face,
        }
        converter = dispatch.get(seg.get("type", ""))
        if converter is None:
            logger.warning(f"不支持的 OneBot segment 类型: {seg.get('type', '')}")
            return None
        return await converter(None, seg, depth)

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
            root = ET.fromstring(
                re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_content)
            )
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
        except Exception as e:
            logger.warning(f"get_msg({message_id}) 异常: {e}")
            return None
        return result if isinstance(result, dict) else None

    async def fetch_record_text(self, message_id: str) -> str | None:
        """通过 OneBot API fetch_ptt_text 获取语音转文字结果。"""
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action("fetch_ptt_text", message_id=message_id),
            )
        except Exception as e:
            logger.warning(f"fetch_ptt_text({message_id}) 异常: {e}")
            return None
        if isinstance(result, dict):
            return result.get("text")
        return None

    async def get_group_member(self, user_id: str | None = None) -> dict | None:
        """通过 get_group_member_info 获取群名片或昵称。

        Args:
            user_id: 目标用户 ID，为空时取当前事件发送者。

        Returns:
            OneBot API 返回的成员信息 dict，失败时为 None。
        """
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
        except Exception as e:
            logger.warning(f"get_group_member_info({user_id}) 异常: {e}")
            return None
        if isinstance(result, dict):
            return result
        return None

    async def get_stranger(self, user_id: str | None = None) -> dict | None:
        """通过 get_stranger_info 获取 QQ 昵称。

        Args:
            user_id: 目标用户 ID，为空时取当前事件发送者。

        Returns:
            OneBot API 返回的用户信息 dict，失败时为 None。
        """
        if user_id is None:
            user_id = self._event.get_sender_id()
        call_action = self._event.bot.api.call_action
        try:
            result = await async_retry(
                lambda: call_action("get_stranger_info", user_id=user_id),
            )
        except Exception as e:
            logger.warning(f"get_stranger_info({user_id}) 异常: {e}")
            return None
        if isinstance(result, dict):
            return result
        return None
