from typing import Any


class EnhancedSender:
    """Sender info for EnhancedNode."""

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
    """Base for all Enhanced types. Subclasses set type."""

    type: str

    def to_dict(self) -> dict[str, Any]:
        """Auto-scan instance fields, skip _* / None / empty."""
        result: dict[str, Any] = {"type": self.type}
        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue
            if value is None or value == "":
                continue
            result[key] = value
        return result


# ---- Plain ----

class EnhancedPlain(EnhancedComponent):
    type = "text"
    text: str | None

    def __init__(self, text: str | None = None):
        self.text = text


# ---- Mention ----

class EnhancedMention(EnhancedComponent):
    type = "mention"

    def __init__(self, id: str = "", name: str = ""):
        self.id = id
        self.name = name


# ---- Mention All ----

class EnhancedMentionAll(EnhancedComponent):
    type = "mention_all"


# ---- File ----

class EnhancedFile(EnhancedComponent):
    type = "file"
    name: str | None
    url: str | None
    path: str | None
    warn: str | None

    def __init__(self, name: str | None = None, url: str | None = None):
        self.name = name
        self.url = url


# ---- Image / Sticker ----

class EnhancedImage(EnhancedComponent):
    type = "image"
    url: str | None
    path: str | None
    warn: str | None

    def __init__(self, url: str | None = None):
        self.url = url


class EnhancedSticker(EnhancedComponent):
    type = "sticker"
    url: str | None
    path: str | None
    summary: str | None
    warn: str | None

    def __init__(self, url: str | None = None, summary: str | None = None):
        self.url = url
        self.summary = summary


# ---- Video ----

class EnhancedVideo(EnhancedComponent):
    type = "video"
    url: str | None
    path: str | None
    warn: str | None

    def __init__(self, url: str | None = None):
        self.url = url


# ---- Voice ----

class EnhancedVoice(EnhancedComponent):
    type = "voice"
    url: str | None
    path: str | None
    text: str | None
    warn: str | None

    def __init__(self, url: str | None = None, text: str | None = None):
        self.url = url
        self.text = text


# ---- Reply ----

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


# ---- Face ----

class EnhancedFace(EnhancedComponent):
    type = "face"
    id: str | None

    def __init__(self, id: str | None = None):
        self.id = id


# ---- Json ----

class EnhancedJson(EnhancedComponent):
    type = "json"
    data: str | None

    def __init__(self, data: str | None = None):
        self.data = data


# ---- Forward ----

class EnhancedForward(EnhancedComponent):
    type = "forward"
    id: str | None
    summary: str | None = None
    messages: list[EnhancedComponent] | None

    def __init__(self, id: str | None = None, summary: str | None = None, messages: list[EnhancedComponent] | None = None):
        self.id = id
        self.summary = summary
        self.messages = messages


# ---- Nodes ----

class EnhancedNodes(EnhancedComponent):
    type = "nodes"
    summary: str | None = None
    messages: list[EnhancedComponent] | None

    def __init__(self, summary: str | None = None, messages: list[EnhancedComponent] | None = None):
        self.summary = summary
        self.messages = messages


# ---- Node ----

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


# ---- Share ----

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


# ---- Music ----

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
    """Build a human-readable summary string from an Enhanced chain."""
    parts: list[str] = []
    for comp in chain:
        if isinstance(comp, EnhancedPlain):
            if comp.text:
                parts.append(comp.text)
        elif isinstance(comp, EnhancedImage):
            parts.append("[图片]")
        elif isinstance(comp, EnhancedSticker):
            summary = getattr(comp, "summary", None)
            if summary:
                parts.append(f"[贴纸:{summary}]")
            else:
                parts.append("[贴纸]")
        elif isinstance(comp, EnhancedFace):
            parts.append(f"[表情:{comp.id}]")
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
