"""插件通用工具函数。"""

import asyncio
from typing import Any, Awaitable, Callable

from astrbot.api import logger


async def async_retry(
    action: Callable[[], Awaitable[Any]],
    action_name: str,
    max_retries: int = 3,
    delay: float = 5.0,
) -> Any | None:
    """带重试的异步调用封装。

    Args:
        action: 异步可调用对象。
        action_name: 操作名称（用于日志）。
        max_retries: 最大重试次数。
        delay: 重试间隔（秒）。

    Returns:
        成功时返回结果，全部失败返回 None。
    """
    for attempt in range(max_retries):
        try:
            return await action()
        except Exception as e:
            logger.debug(f"{action_name} 失败(尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
    logger.debug(f"{action_name}: {max_retries} 次重试均失败")
    return None


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
