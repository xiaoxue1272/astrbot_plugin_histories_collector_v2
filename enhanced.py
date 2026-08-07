from abc import ABC, abstractmethod
from typing import Any

from astrbot.core.utils.media_utils import MediaResolver


class EnhancedSender:
    """EnhancedNode 的发送者信息。"""

    id: str | None
    name: str | None
    nickname: str | None

    def __init__(self, id: str | None = None, name: str | None = None, nickname: str | None = None):
        self.id = id
        self.name = name
        self.nickname = nickname

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.id:
            result["id"] = self.id
        if self.name:
            result["name"] = self.name
        if self.nickname:
            result["nickname"] = self.nickname
        return result


class EnhancedComponent:
    """Enhanced 类型基类，子类设置 type。"""

    type: str

    def to_dict(self) -> dict[str, Any]:
        """自动扫描实例字段，跳过 _* / None / 空字符串。"""
        result: dict[str, Any] = {"type": self.type}
        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue
            if value is None or value == "":
                continue
            result[key] = value
        return result


# ---- 文本 ----

class EnhancedDownloadableComponent(EnhancedComponent, ABC):
    """可下载媒体组件的抽象基类。

    子类实现 download() 返回本地文件路径。
    """

    url: str | None
    path: str | None
    warn: str | None

    @abstractmethod
    async def download(self) -> str | None:
        """下载媒体文件，返回本地临时文件路径。失败返回 None。"""
        ...


class EnhancedPlain(EnhancedComponent):
    type = "text"
    text: str | None

    def __init__(self, text: str | None = None):
        self.text = text


# ---- @提及 ----

class EnhancedMention(EnhancedComponent):
    type = "mention"

    def __init__(self, id: str = "", name: str = ""):
        self.id = id
        self.name = name


# ---- @全体成员 ----

class EnhancedMentionAll(EnhancedComponent):
    type = "mention_all"


# ---- 文件 ----

class EnhancedFile(EnhancedDownloadableComponent):
    type = "file"
    name: str | None

    def __init__(self, name: str | None = None, url: str | None = None):
        self.name = name
        self.url = url

    async def download(self) -> str | None:
        """下载文件到本地临时目录，返回临时路径。"""
        import uuid
        from pathlib import Path

        from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
        from astrbot.core.utils.io import download_file

        if not self.url:
            return None
        download_dir = Path(get_astrbot_temp_path())
        download_dir.mkdir(parents=True, exist_ok=True)
        if self.name:
            filename = self.name
        else:
            filename = f"fileseg_{uuid.uuid4().hex}"
        file_path = download_dir / filename
        await download_file(self.url, str(file_path))
        return str(file_path.resolve())


# ---- 图片 / 贴纸 ----

class EnhancedImage(EnhancedDownloadableComponent):
    type = "image"

    def __init__(self, url: str | None = None):
        self.url = url

    async def download(self) -> str | None:
        from astrbot.core.utils.media_utils import MediaResolver
        if not self.url:
            return None
        return await MediaResolver(self.url, media_type="image").to_path()


class EnhancedSticker(EnhancedDownloadableComponent):
    type = "sticker"
    summary: str | None

    def __init__(self, url: str | None = None, summary: str | None = None):
        self.url = url
        self.summary = summary

    async def download(self) -> str | None:
        if not self.url:
            return None
        return await MediaResolver(self.url, media_type="image").to_path()


# ---- 视频 ----

class EnhancedVideo(EnhancedDownloadableComponent):
    type = "video"

    def __init__(self, url: str | None = None):
        self.url = url

    async def download(self) -> str | None:
        if not self.url:
            return None
        return await MediaResolver(self.url, media_type="video", default_suffix=".mp4").to_path()


# ---- 语音 ----

class EnhancedVoice(EnhancedDownloadableComponent):
    type = "voice"
    text: str | None

    def __init__(self, url: str | None = None, text: str | None = None):
        self.url = url
        self.text = text

    async def download(self) -> str | None:
        if not self.url:
            return None
        return await MediaResolver(self.url, media_type="audio", default_suffix=".wav").to_path(target_format="wav")


# ---- 引用回复 ----

class EnhancedReply(EnhancedComponent):
    type = "reply"
    id: str | None
    messages: list[EnhancedComponent] | None
    sender_id: str | None
    sender_name: str | None
    sender_nickname: str | None
    time: int | None

    def __init__(self, id: str | None = None, messages: list[EnhancedComponent] | None = None,
                 sender_id: str | None = None, sender_name: str | None = None,
                 sender_nickname: str | None = None, time: int | None = None):
        self.id = id
        self.messages = messages
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.sender_nickname = sender_nickname
        self.time = time


# ---- 表情 ----

class EnhancedFace(EnhancedComponent):
    type = "face"
    id: str | None

    def __init__(self, id: str | None = None):
        self.id = id


# ---- JSON ----

class EnhancedJson(EnhancedComponent):
    type = "json"
    data: str | None

    def __init__(self, data: str | None = None):
        self.data = data


# ---- 转发消息 ----

class EnhancedForward(EnhancedComponent):
    type = "forward"
    id: str | None
    summary: str | None = None
    messages: list[EnhancedComponent] | None

    def __init__(self, id: str | None = None, summary: str | None = None, messages: list[EnhancedComponent] | None = None):
        self.id = id
        self.summary = summary
        self.messages = messages


# ---- 合并转发节点列表 ----

class EnhancedNodes(EnhancedComponent):
    type = "nodes"
    summary: str | None = None
    messages: list[EnhancedComponent] | None

    def __init__(self, summary: str | None = None, messages: list[EnhancedComponent] | None = None):
        self.summary = summary
        self.messages = messages


# ---- 转发节点 ----

class EnhancedNode(EnhancedComponent):
    type = "node"
    sender: EnhancedSender | None = None
    messages: list[EnhancedComponent] | None
    time: int | None

    def __init__(self, sender_id: str | None = None, sender_name: str | None = None,
                 sender_nickname: str | None = None, messages: list[EnhancedComponent] | None = None,
                 time: int | None = None):
        self.sender = None
        if sender_id:
            self.sender = EnhancedSender(id=sender_id, name=sender_name, nickname=sender_nickname)
        self.messages = messages
        self.time = time

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.sender is not None:
            result["sender"] = self.sender.to_dict()
        return result


# ---- 分享 ----

class EnhancedShare(EnhancedComponent):
    type = "share"
    url: str | None
    title: str | None
    content: str | None
    image: str | None

    def __init__(self, url: str | None = None, title: str | None = None,
                 content: str | None = None, image: str | None = None):
        self.url = url
        self.title = title
        self.content = content
        self.image = image


# ---- 音乐 ----

class EnhancedMusic(EnhancedComponent):
    type = "music"
    source: str | None = None
    id: int | None = None
    url: str | None = None
    audio: str | None = None
    title: str | None = None
    content: str | None = None
    image: str | None = None

    def __init__(self, source: str | None = None, id: int | None = None,
                 url: str | None = None, audio: str | None = None,
                 title: str | None = None, content: str | None = None,
                 image: str | None = None):
        self.source = source
        self.id = id
        self.url = url
        self.audio = audio
        self.title = title
        self.content = content
        self.image = image


def build_summary(chain: list[EnhancedComponent]) -> str:
    """将 Enhanced 消息链构建为可读摘要字符串。"""
    parts: list[str] = []
    for comp in chain:
        if isinstance(comp, EnhancedPlain):
            if comp.text:
                parts.append(comp.text)
        elif isinstance(comp, EnhancedImage):
            parts.append("[图片]")
        elif isinstance(comp, EnhancedSticker):
            if comp.summary is not None:
                parts.append(f"[动画表情:{comp.summary}]")
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
            reply_messages = comp.messages or []
            inner = build_summary(reply_messages)
            if comp.sender_nickname and inner:
                parts.append(f"[引用消息:({comp.sender_nickname}:{inner})]")
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
