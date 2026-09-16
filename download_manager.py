import asyncio
import hashlib
import mimetypes
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
from astrbot.core.utils.media_utils import MediaResolver
from data.plugins.astrbot_plugin_histories_collector_v2.enhanced import (
    EnhancedDownloadable,
    EnhancedFile,
    EnhancedMedia,
)
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

    # 下载超时：连接 10s 快速失败，整体 30 分钟上限
    _DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(connect=10, total=1800)

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

    async def download_and_cache(self, comp: EnhancedDownloadable):
        """下载媒体文件并缓存到本地存储，结果写入 comp.path / comp.warn。

        流程：单次请求下载（内含大小校验）→ 媒体类型再经 MediaResolver 加工 → 缓存入库。

        Args:
            comp: 可下载的 Enhanced 组件。
        """
        url = comp.url or ""
        if not url:
            logger.debug(f"跳过下载: url 为空, type={comp.type}")
            return

        try:
            temp_path, warning = await self._download(comp)
        except Exception as e:
            logger.warning(f"下载失败: {e}, url={url[:80]}")
            comp.warn = "下载失败"
            return

        if warning:
            comp.warn = warning
            return
        if not temp_path:
            comp.warn = "下载失败"
            return

        # 媒体类型：拿下载后的本地路径继续走 MediaResolver（音频转码等）
        if isinstance(comp, EnhancedMedia):
            try:
                resolved_path = await MediaResolver(
                    temp_path,
                    media_type=comp.media_type,
                ).to_path()
            except Exception as e:
                logger.warning(f"媒体处理失败: {e}, path={temp_path}")
                self._cleanup_temp(temp_path)
                comp.warn = "媒体处理失败"
                return
            if resolved_path != temp_path:
                # 转码产生了新文件，清理中间文件
                self._cleanup_temp(temp_path)
            temp_path = resolved_path

        file_name = getattr(comp, "name", "") or ""
        cached_path, warning = self._cache(temp_path, comp.type, file_name=file_name)
        if cached_path:
            comp.path = cached_path
            logger.debug(f"文件已缓存: type={comp.type}, path={cached_path}")
        if warning:
            comp.warn = warning

    async def _download(self, comp: EnhancedDownloadable) -> tuple[str | None, str | None]:
        """单次 HTTP 请求内完成大小校验并下载到临时文件。

        由本管理器统一负责下载：既避免 MediaResolver 对 HTTP 图片硬编码 ".bin" 后缀，
        也省去「先预检再下载」的重复建连开销。

        Args:
            comp: 可下载组件。

        Returns:
            (临时文件绝对路径, 警告信息)。超限时路径为 None 且警告非 None。
        """
        url = comp.url or ""
        if not url:
            return None, "下载失败"

        temp_dir = Path(get_astrbot_temp_path())
        temp_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = self.max_file_size_bytes

        async with self._http_session.get(url, timeout=self._DOWNLOAD_TIMEOUT) as resp:
            if not 200 <= resp.status < 300:
                raise RuntimeError(f"下载返回错误状态码: {resp.status}")

            logger.debug(f"url={url} headers={dict(resp.headers)}")
            content_type = resp.headers.get("Content-Type")
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                logger.debug(f"文件超出大小限制 ({content_length} 字节)，跳过: {url[:80]}")
                return None, (
                    f"文件超出 {self._max_file_size_mb}MB 限制 "
                    f"({format_bytes_to_mb(int(content_length))})"
                )

            file_name = getattr(comp, "name", "") or ""
            if isinstance(comp, EnhancedFile) and file_name:
                # 文件类型保留原始文件名
                filename = self._sanitize_filename(file_name)
            else:
                suffix = self._pick_suffix(comp.type, content_type)
                filename = f"{comp.type}_{uuid.uuid4().hex}{suffix}"

            temp_path = temp_dir / filename
            downloaded = 0
            over_limit = False
            try:
                with open(temp_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            # 兜底：无 Content-Length 时按实际字节数中断
                            over_limit = True
                            break
                        f.write(chunk)
            except Exception:
                self._cleanup_temp(str(temp_path))
                raise

        if over_limit:
            self._cleanup_temp(str(temp_path))
            return None, f"文件超出 {self._max_file_size_mb}MB 限制"

        return str(temp_path.resolve()), None

    @staticmethod
    def _pick_suffix(file_type: str, content_type: str | None) -> str:
        """决定临时文件后缀：优先 Content-Type，回退到类型默认后缀。

        Args:
            file_type: 组件类型（image/sticker/video/voice/file）。
            content_type: HTTP 响应头 Content-Type，可能为 None。

        Returns:
            含点的后缀字符串，无法确定时返回空字符串。
        """
        guessed: str | None = None
        if content_type:
            mime = content_type.split(";")[0].strip().lower()
            guessed = mimetypes.guess_extension(mime)
        return guessed or DownloadManager._EXT_FALLBACK.get(file_type, "")

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
