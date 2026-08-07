import asyncio
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from data.plugins.astrbot_plugin_histories_collector_v2.enhanced import EnhancedDownloadableComponent
from data.plugins.astrbot_plugin_histories_collector_v2.utils import (
    format_bytes_to_mb,
    get_plugin_data_dir,
)


class DownloadManager:
    """媒体文件下载与缓存管理器。

    管理 aiohttp session 生命周期，预检文件大小，下载后通过内容哈希去重。
    """

    _EXT_FALLBACK: dict[str, str] = {
        "image": ".jpg",
        "sticker": ".jpg",
        "video": ".mp4",
        "voice": ".amr",
    }

    def __init__(
        self,
        max_file_size_mb: int = 50,
    ) -> None:
        self._max_file_size_mb = max_file_size_mb
        self._store_dir = get_plugin_data_dir()
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._http_session: aiohttp.ClientSession = aiohttp.ClientSession()
        self._http_session_lock = asyncio.Lock()

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_mb * 1024 * 1024

    # ── 生命周期 ─

    async def close(self) -> None:
        """关闭管理器，清理 HTTP session。"""
        await self._http_session.close()

    # ── 公共接口 ──

    async def check_size(self, url: str) -> str | None:
        """通过 HTTP Content-Length 预检文件大小，返回警告信息或 None。

        Args:
            url: 文件 URL。

        Returns:
            超限时返回警告字符串，否则返回 None（含预检失败）。
        """
        try:
            async with self._http_session.get(url, timeout=10) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_file_size_bytes:
                    logger.info(f"文件超出大小限制 ({content_length} 字节)，跳过: {url[:80]}")
                    return f"文件超出 {self._max_file_size_mb}MB 限制 ({format_bytes_to_mb(int(content_length))})"
        except Exception as e:
            logger.warning(f"预检文件大小失败 ({url[:80]}): {e}")
            return "文件大小校验失败"
        return None

    async def download_and_cache(self, comp: EnhancedDownloadableComponent):
        """下载媒体文件并缓存到本地存储，结果写入 comp.path / comp.warn。

        Args:
            comp: 可下载的 Enhanced 组件。
        """
        url = comp.url or ""
        if not url:
            logger.debug(f"跳过下载: url 为空, type={comp.type}")
            return

        warning = await self.check_size(url)
        if warning:
            comp.warn = warning
            return

        try:
            temp_path = await comp.download()
        except Exception as e:
            logger.warning(f"下载失败: {e}, url={url[:80]}")
            comp.warn = "下载失败"
            return

        if not temp_path:
            comp.warn = "下载失败"
            return

        file_name = getattr(comp, "name", "") or ""
        cached_path, warning = self._cache(temp_path, comp.type, file_name=file_name)
        if cached_path:
            comp.path = cached_path
            logger.debug(f"文件已缓存: type={comp.type}, path={cached_path}")
        if warning:
            comp.warn = warning

    # ── 哈希 / 路径辅助 ──

    @staticmethod
    def _compute_hash(file_path: str, algo: str = "md5") -> str:
        h = hashlib.new(algo)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _extract_extension(file_path: str, file_type: str) -> str:
        suffix = Path(file_path).suffix
        if suffix and len(suffix) <= 8:
            return suffix.lower()
        return DownloadManager._EXT_FALLBACK.get(file_type, "")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """移除文件系统不允许的字符。"""
        return "".join(c for c in name if c not in r'<>:"/\|?*')

    def _build_store_path(
        self,
        file_type: str,
        content_hash: str = "",
        extension: str = "",
        file_name: str = "",
    ) -> Path:
        sub_dir = self._store_dir / file_type
        if file_type == "sticker":
            sub_dir = sub_dir / extension.lstrip(".")
        else:
            now = datetime.now()
            sub_dir = sub_dir / str(now.year) / f"{now.month:02d}"
        sub_dir.mkdir(parents=True, exist_ok=True)

        if file_name:
            safe_name = self._sanitize_filename(file_name)
            return sub_dir / safe_name

        return sub_dir / f"{content_hash[:16]}{extension}"

    def _cache(
        self,
        temp_path: str,
        file_type: str,
        file_name: str = "",
    ) -> tuple[str | None, str | None]:
        """缓存本地文件到存储目录，返回 (相对路径, 警告信息)。"""
        if not temp_path:
            return None, "下载失败"

        if file_type == "file" and file_name:
            dest = self._build_store_path(file_type, file_name=file_name)
            if dest.exists():
                self._cleanup_temp(temp_path)
                return dest.relative_to(self._store_dir).as_posix(), None
            shutil.copy(temp_path, dest)
            self._cleanup_temp(temp_path)
            return dest.relative_to(self._store_dir).as_posix(), None

        md5_hash = self._compute_hash(temp_path, "md5")
        extension = self._extract_extension(temp_path, file_type)
        dest = self._build_store_path(file_type, md5_hash, extension)

        if dest.exists():
            new_sha256 = self._compute_hash(temp_path, "sha256")
            existing_sha256 = self._compute_hash(str(dest), "sha256")
            if new_sha256 == existing_sha256:
                self._cleanup_temp(temp_path)
                return dest.relative_to(self._store_dir).as_posix(), None
            logger.info(f"MD5 碰撞: {temp_path}，改用 SHA-256 命名")
            dest = self._build_store_path(file_type, new_sha256, extension)
            if dest.exists():
                self._cleanup_temp(temp_path)
                return dest.relative_to(self._store_dir).as_posix(), None

        shutil.copy(temp_path, dest)
        self._cleanup_temp(temp_path)
        return dest.relative_to(self._store_dir).as_posix(), None

    @staticmethod
    def _cleanup_temp(temp_path: str) -> None:
        """删除临时文件。"""
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
