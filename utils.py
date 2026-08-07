"""插件通用工具函数。"""

from pathlib import Path
from typing import Any, Awaitable, Callable

PLUGIN_NAME = "astrbot_plugin_histories_collector_v2"


async def async_retry(
    action: Callable[[], Awaitable[Any | None]],
    max_retries: int = 3,
    delay: float | Callable[[int], float] = 5.0,
) -> Any | None:
    """带重试的异步调用封装。

    全部失败时重新抛出最后一次异常。

    Args:
        action: 异步可调用对象。
        max_retries: 最大重试次数。
        delay: 重试间隔（秒），也支持 callable(attempt) 实现动态延迟（如指数退避）。

    Returns:
        成功时返回 action 的结果。

    Raises:
        Exception: 重试次数用尽，抛出最后一次 action 的异常。
    """
    import asyncio

    last_error = None
    for attempt in range(max_retries):
        try:
            return await action()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                current_delay = delay(attempt) if callable(delay) else delay
                await asyncio.sleep(current_delay)
    raise last_error


def is_http_url(url: str) -> bool:
    """判断字符串是否为 HTTP/HTTPS 链接。

    Args:
        url: 待检查的字符串。

    Returns:
        True 表示是 HTTP 链接。
    """
    return url.startswith("http://") or url.startswith("https://")


def format_bytes_to_mb(size_bytes: int) -> str:
    """将字节数格式化为可读的 MB 字符串。

    Args:
        size_bytes: 字节数。

    Returns:
        格式化后的字符串，如 "3.85 MB"。
    """
    return f"{size_bytes / 1024 / 1024:.2f} MB"


def get_plugin_data_dir() -> Path:
    """返回插件数据目录路径。"""
    from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
    return Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
