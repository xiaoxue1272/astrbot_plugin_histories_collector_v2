"""插件通用工具函数。"""


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
