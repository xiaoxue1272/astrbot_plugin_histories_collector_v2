from astrbot.api import logger

from data.plugins.astrbot_plugin_histories_collector_v2.config import GroupFilterConfig


class GroupFilter:
    """群组过滤器，支持白名单、黑名单模式。

    每个平台独立维护各自的群组 ID 集合。
    """

    MODE_WHITELIST = "whitelist"
    MODE_BLACKLIST = "blacklist"

    def __init__(self, config: GroupFilterConfig):
        self._mode = config.mode

        self._platform_groups: dict[str, set[str]] = {}
        for entry in config.platforms:
            platform = entry.get("platform", "")
            group_ids = entry.get("group_ids", [])
            if platform and group_ids:
                self._platform_groups[platform] = set(str(g) for g in group_ids)

    def should_collect(self, platform_name: str, group_id: str) -> bool:
        """判断某条群消息是否应被收集。

        Args:
            platform_name: 平台类型名称，如 "aiocqhttp"、"telegram"。
            group_id: 群组 ID。

        Returns:
            True 表示应收集，False 表示应过滤。
        """

        target_set = self._platform_groups.get(platform_name, set())

        if self._mode == self.MODE_WHITELIST:
            return group_id in target_set

        if self._mode == self.MODE_BLACKLIST:
            return group_id not in target_set

        logger.warning(f"未知的群组过滤模式 '{self._mode}'，默认放行全部。")
        return True
