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

        # 同一平台允许配置多条，群组 ID 需要合并而不是互相覆盖
        self._platform_groups: dict[str, set[str]] = {}
        for entry in config.platforms:
            platform = entry.get("platform", "")
            group_ids = entry.get("group_ids", [])
            if not platform:
                continue
            groups = {str(g) for g in group_ids if str(g)}
            self._platform_groups.setdefault(platform, set()).update(groups)

    def should_collect(self, platform_name: str, group_id: str) -> bool:
        """判断某条群消息是否应被收集。

        Args:
            platform_name: 平台类型名称，如 "aiocqhttp"、"telegram"。
            group_id: 群组 ID。

        Returns:
            True 表示应收集，False 表示应过滤。
        """
        # 部分平台的 group_id 是 int，与配置中的字符串统一后再比较
        group_id = str(group_id) if group_id else ""

        target_set = self._platform_groups.get(platform_name, set())

        if self._mode == self.MODE_WHITELIST:
            return group_id in target_set

        if self._mode == self.MODE_BLACKLIST:
            return group_id not in target_set

        logger.warning(f"未知的群组过滤模式 '{self._mode}'，默认放行全部。")
        return True
