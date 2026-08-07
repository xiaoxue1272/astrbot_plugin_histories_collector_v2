from typing import Any


class ESConfig:
    """Elasticsearch 连接配置。"""

    hosts: list[str]
    user: str
    password: str
    alias: str
    use_ik_analyzer: bool

    def __init__(self, config: dict[str, Any]):
        self.hosts = config.get('hosts', ['localhost:9200'])
        self.user = config.get('user', '')
        self.password = config.get('password', '')
        self.alias = config.get('alias', 'message-histories-v2')
        self.use_ik_analyzer = config.get('use_ik_analyzer', True)


class GroupFilterConfig:
    """群组过滤配置，支持按模式和平台分组列表过滤。"""

    mode: str
    platforms: list[dict]

    def __init__(self, config: dict[str, Any]):
        self.mode = config.get('mode', 'whitelist')
        self.platforms = config.get('platforms', [])


class HistoriesCollectorConfig:
    """插件配置包装器。"""

    es_config: ESConfig
    group_filter: GroupFilterConfig
    max_file_size_mb: int
    max_nesting_depth: int

    def __init__(self, config: dict[str, Any]):
        self.es_config = ESConfig(config.get('es_config', {}))
        self.group_filter = GroupFilterConfig(config.get('group_filter', {}))
        self.max_file_size_mb = config.get('max_file_size_mb', 50)
        self.max_nesting_depth = config.get('max_nesting_depth', 3)
