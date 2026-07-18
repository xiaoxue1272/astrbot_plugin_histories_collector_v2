from data.plugins.astrbot_plugin_histories_collector_v2.config import GroupFilterConfig


class GroupFilter:
    """Group filter supporting whitelist, blacklist, and disabled modes.

    Each platform maintains its own group ID set independently.
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
        """Determine whether a group message should be collected.

        Args:
            platform_name: Platform type name, e.g. "aiocqhttp", "telegram".
            group_id: Group ID from event.get_group_id().

        Returns:
            True if the message should be collected, False otherwise.
        """

        target_set = self._platform_groups.get(platform_name, set())

        if self._mode == self.MODE_WHITELIST:
            return group_id in target_set

        if self._mode == self.MODE_BLACKLIST:
            return group_id not in target_set

        return True
