"""消息链摘要生成。

把 Enhanced 消息链拼成可读的纯文本摘要，属于展示逻辑，
与组件定义（enhanced.py）解耦。
"""

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
    EnhancedNodes,
    EnhancedPlain,
    EnhancedReply,
    EnhancedShare,
    EnhancedSticker,
    EnhancedVideo,
    EnhancedVoice,
)


def build_summary(chain: list[EnhancedComponent]) -> str:
    """将 Enhanced 消息链构建为可读摘要字符串。

    Args:
        chain: Enhanced 消息链。

    Returns:
        以空格连接的摘要文本。
    """
    parts: list[str] = []
    for comp in chain:
        if isinstance(comp, EnhancedPlain):
            if comp.text:
                parts.append(comp.text)
        elif isinstance(comp, EnhancedImage):
            parts.append("[图片]")
        elif isinstance(comp, EnhancedSticker):
            if comp.summary is not None:
                parts.append(comp.summary)
            else:
                parts.append("[动画表情]")
        elif isinstance(comp, EnhancedFace):
            if comp.id is not None:
                parts.append(f"[表情:{comp.id}]")
            else:
                parts.append("[表情]")
        elif isinstance(comp, EnhancedMention):
            parts.append(f"[@:{comp.name}]")
        elif isinstance(comp, EnhancedMentionAll):
            parts.append("[@全体成员]")
        elif isinstance(comp, EnhancedReply):
            reply_messages = [c for c in (comp.messages or []) if not isinstance(c, EnhancedReply)]
            inner_summary = build_summary(reply_messages)
            name = comp.sender_nickname if comp.sender_nickname else comp.sender_name
            if name and inner_summary:
                parts.append(f"[引用消息:({name}:{inner_summary})]")
            else:
                parts.append("[引用消息]")
        elif isinstance(comp, EnhancedVoice):
            if comp.text:
                parts.append(f"[语音:({comp.text})]")
            else:
                parts.append("[语音]")
        elif isinstance(comp, EnhancedVideo):
            parts.append("[视频]")
        elif isinstance(comp, EnhancedFile):
            parts.append("[文件]")
        elif isinstance(comp, EnhancedJson):
            parts.append("[JSON]")
        elif isinstance(comp, EnhancedMusic):
            parts.append("[音乐]")
        elif isinstance(comp, EnhancedShare):
            parts.append("[分享]")
        elif isinstance(comp, (EnhancedForward, EnhancedNodes)):
            summary = getattr(comp, "summary", "")
            if summary:
                parts.append(f"[聊天记录:{summary}]")
            else:
                parts.append("[聊天记录]")
        else:
            parts.append(f"[{comp.type}]")
    return " ".join(parts).strip()
