from typing import Any


class ESConfig:
    """Elasticsearch 连接配置。"""

    hosts: list[str]
    user: str
    password: str
    alias: str
    use_ik_analyzer: bool
    number_of_replicas: int

    def __init__(self, config: dict[str, Any]):
        # 空列表同样回退到默认地址，避免 ES 客户端缺少 hosts 直接报错
        self.hosts = config.get("hosts") or ["http://localhost:9200"]
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        self.alias = config.get("alias", "message-histories-v2")
        self.use_ik_analyzer = config.get("use_ik_analyzer", True)
        self.number_of_replicas = int(config.get("number_of_replicas", 0))

    @property
    def http_auth(self) -> tuple[str, str] | None:
        """返回 ES 认证元组；用户名与密码都为空时返回 None。

        Returns:
            (user, password) 二元组，未配置认证时为 None。
        """
        if not self.user and not self.password:
            return None
        return (self.user, self.password)


class GroupFilterConfig:
    """群组过滤配置，支持按模式和平台分组列表过滤。"""

    mode: str
    platforms: list[dict]

    def __init__(self, config: dict[str, Any]):
        self.mode = config.get("mode", "whitelist")
        self.platforms = config.get("platforms", [])


class HistoriesCollectorConfig:
    """插件配置包装器。"""

    es_config: ESConfig
    group_filter: GroupFilterConfig
    max_file_size_mb: int
    max_nesting_depth: int
    collect_bot_message: bool
    parse_types: list[str]
    download_types: list[str]

    def __init__(self, config: dict[str, Any]):
        self.es_config = ESConfig(config.get("es_config", {}))
        self.group_filter = GroupFilterConfig(config.get("group_filter", {}))
        self.max_file_size_mb = config.get("max_file_size_mb", 50)
        self.max_nesting_depth = config.get("max_nesting_depth", 3)
        self.collect_bot_message = bool(config.get("collect_bot_message", False))
        # 需要解析的消息组件类型，空表示全部解析
        self.parse_types = list(config.get("parse_types") or [])
        # 需要下载的媒体类型，空表示全部下载
        self.download_types = list(config.get("download_types") or [])
