from typing import Any


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
        """自动扫描实例字段，跳过 _* / None / 空字符串，递归转换嵌套组件。"""
        result: dict[str, Any] = {"type": self.type}
        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue
            if value is None or value == "":
                continue
            if isinstance(value, EnhancedComponent):
                result[key] = value.to_dict()
            elif isinstance(value, list):
                result[key] = [
                    item.to_dict() if isinstance(item, EnhancedComponent) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result


# ---- 媒体 mixin ----

class EnhancedMedia:
    """mixin：需要 MediaResolver 加工的组件（目前仅音频转码）。

    ``media_type`` 供 ``DownloadManager`` 决定调用 ``MediaResolver`` 的参数。
    本类不继承任何基类，与 ``EnhancedFile`` 组合使用以避免钻石继承。
    """

    media_type: str


# ---- 文本 ----

class EnhancedPlain(EnhancedComponent):
    type = "text"
    text: str | None

    def __init__(self, text: str | None = None):
        self.text = text


# ---- @提及 ----

class EnhancedMention(EnhancedComponent):
    type = "mention"
    id: str | None
    name: str | None
    nickname: str | None

    def __init__(self, id: str | None = "", name: str | None = "", nickname: str | None = ""):
        self.id = id
        self.name = name
        self.nickname = nickname


# ---- @全体成员 ----

class EnhancedMentionAll(EnhancedComponent):
    type = "mention_all"


# ---- 文件（可下载组件基类） ----

class EnhancedFile(EnhancedComponent):
    """可下载组件基类（含 file 类型本身）。

    ``name`` 存放发送方提供的文件名（平台数据或 ``Content-Disposition``），
    ``url`` / ``path`` / ``warn`` 为公共字段；
    下载与命名逻辑统一收敛在 ``DownloadManager``（download_manager.py）。
    """

    type = "file"
    name: str | None
    url: str | None
    path: str | None
    warn: str | None

    def __init__(self, name: str | None = None, url: str | None = None):
        self.name = name
        self.url = url


# ---- 图片 / 贴纸 ----

class EnhancedImage(EnhancedFile):
    type = "image"


class EnhancedSticker(EnhancedFile):
    type = "sticker"
    summary: str | None

    def __init__(self, name: str | None = None, url: str | None = None, summary: str | None = None):
        super().__init__(name=name, url=url)
        self.summary = summary


# ---- 视频 ----

class EnhancedVideo(EnhancedFile):
    type = "video"


# ---- 语音 ----

class EnhancedVoice(EnhancedFile, EnhancedMedia):
    type = "voice"
    media_type = "audio"
    text: str | None

    def __init__(self, name: str | None = None, url: str | None = None, text: str | None = None):
        super().__init__(name=name, url=url)
        self.text = text


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
