import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.core.message.components import File, Image, Record, Video
from data.plugins.astrbot_plugin_histories_collector_v2.utils import (
    format_bytes_to_mb,
    is_http_url,
)


class FileCache:
    """媒体文件下载与缓存管理器。

    负责从消息组件中下载文件、哈希去重、按类型分类存储。
    """

    _TYPE_DIR: dict[type, str] = {
        Image: "image",
        Video: "video",
        Record: "record",
        File: "file",
    }

    _EXT_FALLBACK: dict[type, str] = {
        Image: ".jpg",
        Video: ".mp4",
        Record: ".amr",
    }

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        store_dir: Path,
        max_file_size_mb: int = 50,
    ) -> None:
        self._http_session = http_session
        self._max_file_size_mb = max_file_size_mb
        self._store_dir = store_dir
        self._store_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _compute_hash(file_path: str, algo: str = "md5") -> str:
        h = hashlib.new(algo)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _extract_extension(file_path: str, component) -> str:
        suffix = Path(file_path).suffix
        if suffix and len(suffix) <= 8:
            return suffix.lower()
        return FileCache._EXT_FALLBACK.get(type(component), "")

    def _build_store_path(self, component, content_hash: str, extension: str) -> Path:
        type_dir = self._TYPE_DIR.get(type(component), "file")
        sub_dir = self._store_dir / type_dir
        if isinstance(component, Image):
            sub_dir = sub_dir / extension.lstrip(".")
        else:
            now = datetime.now()
            sub_dir = sub_dir / str(now.year) / f"{now.month:02d}"
        sub_dir.mkdir(parents=True, exist_ok=True)
        return sub_dir / f"{content_hash[:16]}{extension}"

    async def download(
        self,
        component: File | Image | Video | Record,
    ) -> tuple[str | None, str | None]:
        """下载组件文件并缓存，返回 (相对路径, 警告信息)。

        Args:
            component: 可下载的消息组件。

        Returns:
            (相对路径或 None, 警告信息或 None)。
        """
        max_bytes = self._max_file_size_mb * 1024 * 1024

        url = getattr(component, "url", "")
        if url and is_http_url(url):
            try:
                async with self._http_session.get(url, timeout=10) as resp:
                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) > max_bytes:
                        logger.info(f"文件体积超出限制 ({content_length} 字节)，跳过下载: {url[:80]}")
                        return None, f"文件超过 {self._max_file_size_mb}MB 限制 ({format_bytes_to_mb(int(content_length))})"
            except Exception as e:
                logger.warning(f"体积预检失败，跳过下载: {url[:80]}, {e}")
                return None, f"体积预检失败: {e}"

        try:
            if isinstance(component, File):
                temp_path = await component.get_file()
            else:
                temp_path = await component.convert_to_file_path()
        except Exception as e:
            logger.warning(f"文件下载失败: type={component.type}, {e}")
            return None, f"文件不可下载: {e}"

        if not temp_path:
            logger.warning(f"下载失败: 组件类型={component.type}，未返回本地路径")
            return None, "下载失败: 未获取到本地路径"

        file_bytes = Path(temp_path).stat().st_size
        if file_bytes > max_bytes:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
            logger.info(f"文件体积超出限制 ({file_bytes} 字节)，已跳过: {temp_path}")
            return None, f"文件超过 {self._max_file_size_mb}MB 限制 ({format_bytes_to_mb(file_bytes)})"

        md5_hash = self._compute_hash(temp_path, "md5")
        extension = self._extract_extension(temp_path, component)
        dest = self._build_store_path(component, md5_hash, extension)

        if dest.exists():
            new_sha256 = self._compute_hash(temp_path, "sha256")
            existing_sha256 = self._compute_hash(str(dest), "sha256")
            if new_sha256 == existing_sha256:
                logger.debug(f"文件缓存命中: {dest}")
                return dest.relative_to(self._store_dir).as_posix(), None
            logger.warning(f"MD5 碰撞: {temp_path}，改用 SHA-256 命名")
            dest = self._build_store_path(component, new_sha256, extension)

        shutil.copy(temp_path, dest)
        logger.debug(f"文件已缓存: {dest}")
        return dest.relative_to(self._store_dir).as_posix(), None
