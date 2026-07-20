from typing import Any


class ESConfig:
    """Elasticsearch connection configuration."""

    hosts: list[str]
    user: str
    password: str
    alias: str
    use_ik_analyzer: bool

    def __init__(self, config: dict[str, Any]):
        self.hosts = config['hosts']
        self.user = config.get('user', '')
        self.password = config.get('password', '')
        self.alias = config.get('alias', 'message-histories-v2')
        self.use_ik_analyzer = config.get('use_ik_analyzer', True)


class GroupFilterConfig:
    """Group filter configuration with mode and per-platform group lists."""

    mode: str
    platforms: list[dict]

    def __init__(self, config: dict[str, Any]):
        self.mode = config.get('mode', 'whitelist')
        self.platforms = config.get('platforms', [])


class HistoriesCollectorConfig:
    """Plugin configuration wrapper."""

    es_config: ESConfig
    group_filter: GroupFilterConfig
    max_file_size_mb: int
    max_nesting_depth: int

    def __init__(self, config: dict[str, Any]):
        self.es_config = ESConfig(config.get('es_config', {}))
        self.group_filter = GroupFilterConfig(config.get('group_filter', {}))
        self.max_file_size_mb = config.get('max_file_size_mb', 50)
        self.max_nesting_depth = config.get('max_nesting_depth', 3)
