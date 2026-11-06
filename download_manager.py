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
from astrbot.core.utils.media_utils import (
    MediaResolver,
    describe_media_ref,
    file_uri_to_path,
)
from data.plugins.astrbot_plugin_histories_collector_v2.enhanced import (
    EnhancedFile,
    EnhancedMedia,
)
from data.plugins.astrbot_plugin_histories_collector_v2.utils import (
    format_bytes_to_mb,
    get_plugin_data_dir,
    is_http_url,
)


class _MediaError(Exception):
    """可预期的媒体处理失败，消息直接作为 comp.warn 记录到 ES。"""


class DownloadManager:
    """媒体文件下载与缓存管理器。

    对外只有一个入口 ``download_and_cache``，内部是三段流水线：

        _acquire_file → _transform_media → _store_to_data_dir

    依次把媒体引用落实为本地文件、按需做格式加工、按内容哈希入库。
    统一约定：每一步**成功返回 str，失败 raise _MediaError**（意外异常由入口
    兜底）。这样失败原因只在一处转换成 ``comp.warn``，不需要层层判断返回值。

    关于删除：``data/temp`` 是框架多个适配器共用的目录，平台下发的本地文件
    也可能被其他插件引用，因此**本插件在任何分支都不删除来源文件**。
    """

    _EXT_FALLBACK: dict[str, str] = {
        "image": ".jpg",
        "sticker": ".jpg",
        "video": ".mp4",
        "voice": ".amr",
    }

    # 各媒体类型允许的扩展名。QQ 等平台会给动画表情返回 ``<hash>.0``
    # 这类内部类型标记，不能直接当作文件后缀。
    _ALLOWED_EXTENSIONS: dict[str, set[str]] = {
        "image": {".png", ".jpg", ".jpeg", ".jpe", ".gif", ".webp", ".bmp", ".avif"},
        "sticker": {".png", ".jpg", ".jpeg", ".jpe", ".gif", ".webp", ".bmp", ".avif"},
        "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v"},
        "voice": {".amr", ".wav", ".mp3", ".ogg", ".silk", ".m4a", ".aac", ".flac"},
    }

    # 下载超时：连接 10s 快速失败，整体 30 分钟上限
    _DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(connect=10, total=1800)

    def __init__(self, max_file_size_mb: int = 50) -> None:
        self._max_file_size_mb = max_file_size_mb
        self._store_dir = get_plugin_data_dir()
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._http_session: aiohttp.ClientSession = aiohttp.ClientSession()
        # 缓存写入锁：保证同一内容并发落盘时只有一次拷贝，且不会读到半成品
        self._cache_lock = asyncio.Lock()

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_mb * 1024 * 1024

    # ── 生命周期 ──

    async def close(self) -> None:
        """关闭管理器，清理 HTTP session。"""
        await self._http_session.close()

    # ── 公共接口 ──

    async def download_and_cache(self, comp: EnhancedFile) -> None:
        """把组件引用的媒体落到插件数据目录，结果写入 comp.path / comp.warn。

        任一步失败都只写 comp.warn，不向上抛异常：单条媒体不应中断整条消息。
        """
        if comp.path:
            logger.debug(f"跳过下载: 已缓存, type={comp.type}, path={comp.path}")
            return
        url = comp.url or ""
        if not url:
            logger.debug(f"跳过下载: url 为空, type={comp.type}")
            return

        try:
            local_path = await self._acquire_file(comp, url)
            local_path = await self._transform_media(comp, local_path)
            comp.path = await self._store_to_data_dir(local_path, comp.type)
        except _MediaError as e:
            comp.warn = str(e)
        except Exception as e:  # 兜底：磁盘满、权限不足、网络异常等意外错误
            logger.warning(
                f"媒体处理异常: {e}, type={comp.type}, url={describe_media_ref(url)}"
            )
            comp.warn = "处理失败"

    # ── 流水线：取得文件 → 格式加工 → 入库 ──

    async def _acquire_file(self, comp: EnhancedFile, url: str) -> str:
        """把媒体引用落实成一个本地已存在的文件，返回其路径。

        平台下发的媒体引用分两类：HTTP(S) 链接需要下载；本地路径与 ``file://``
        URI（Telegram、企业微信等）本身就是文件，校验存在与大小后原样返回。

        Raises:
            _MediaError: 下载失败、超出大小限制或本地文件不存在。
        """
        if is_http_url(url):
            return await self._download(comp)

        path_str = file_uri_to_path(url)  # 非 file: 输入原样返回
        path = Path(path_str)
        if not path.is_file():
            logger.warning(
                f"本地媒体不存在: type={comp.type}, url={describe_media_ref(url)}"
            )
            raise _MediaError("下载失败")
        # 本地文件与下载产物适用同一大小上限，避免超大文件进入存储目录
        size = path.stat().st_size
        if size > self.max_file_size_bytes:
            raise self._size_limit_error(size)
        return path_str

    @staticmethod
    async def _transform_media(comp: EnhancedFile, local_path: str) -> str:
        """对 EnhancedMedia 组件做格式加工（音频转码等），返回加工后的路径。

        非 EnhancedMedia 组件原样返回。

        Raises:
            _MediaError: MediaResolver 处理失败。
        """
        if not isinstance(comp, EnhancedMedia):
            return local_path
        try:
            return await MediaResolver(
                local_path, media_type=comp.media_type
            ).to_path()
        except Exception as e:
            logger.warning(f"媒体处理失败: {e}, type={comp.type}, path={local_path}")
            raise _MediaError("媒体处理失败") from e

    async def _store_to_data_dir(self, src_path: str, file_type: str) -> str:
        """按内容哈希把文件复制进数据目录，返回相对存储根目录的 posix 路径。

        内容相同天然去重；并发写入同一哈希时先写临时文件再原子替换，避免
        读到半成品。MD5 碰撞（或同哈希不同内容）时退回 SHA-256 命名。
        任何来源文件都不删除。
        """
        extension = self._extract_extension(src_path, file_type)
        md5 = self._compute_hash(src_path, "md5")
        dest = self._build_store_path(file_type, md5, extension)

        if dest.exists():
            src_sha256 = self._compute_hash(src_path, "sha256")
            if src_sha256 == self._compute_hash(str(dest), "sha256"):
                return self._relative(dest)
            logger.info(f"MD5 碰撞: {src_path}，改用 SHA-256 命名")
            dest = self._build_store_path(file_type, src_sha256, extension)
            if dest.exists():
                return self._relative(dest)

        async with self._cache_lock:
            # 加锁后二次检查：另一个协程可能刚刚写入了同一内容
            if not dest.exists():
                staging = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
                try:
                    shutil.copy(src_path, staging)
                    # 同目录下的 os.replace 是原子操作，读者只可能看到完整文件
                    staging.replace(dest)
                finally:
                    staging.unlink(missing_ok=True)

        relative = self._relative(dest)
        logger.debug(f"文件已缓存: type={file_type}, path={relative}")
        return relative

    # ── HTTP 下载 ──

    async def _download(self, comp: EnhancedFile) -> str:
        """下载 HTTP(S) 媒体到框架临时目录，返回绝对路径。

        只负责取回字节并落到本地文件。超限、空内容属可预期失败，抛
        ``_MediaError``；网络 / HTTP 状态码 / 写盘异常向上冒泡，由入口兜底。

        Raises:
            _MediaError: 超出大小限制或下载内容为空。
        """
        url = comp.url or ""
        temp_dir = Path(get_astrbot_temp_path())
        temp_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = self.max_file_size_bytes

        async with self._http_session.get(url, timeout=self._DOWNLOAD_TIMEOUT) as resp:
            if not 200 <= resp.status < 300:
                raise RuntimeError(f"下载返回错误状态码: {resp.status}")

            content_length = self._parse_content_length(
                resp.headers.get("Content-Length")
            )
            if content_length and content_length > max_bytes:
                raise self._size_limit_error(content_length)

            content_type = resp.headers.get("Content-Type")
            # 响应头带文件名时回填 name，用于推断后缀并记录到 ES
            if not comp.name:
                disposition = resp.content_disposition
                if disposition and disposition.filename:
                    comp.name = Path(disposition.filename.replace("\\", "/")).name

            suffix = self._pick_suffix(comp.type, content_type, comp.name or "")
            temp_path = temp_dir / f"{comp.type}_{uuid.uuid4().hex}{suffix}"

            downloaded = 0
            with open(temp_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        # 兜底：无 Content-Length 时按实际字节数中断
                        raise _MediaError(
                            f"文件超出 {self._max_file_size_mb}MB 限制"
                        )
                    f.write(chunk)

        if downloaded == 0:
            logger.warning(
                f"下载内容为空: type={comp.type}, url={describe_media_ref(url)}"
            )
            raise _MediaError("下载内容为空")

        logger.debug(
            f"下载完成: type={comp.type}, size={downloaded}B, suffix={temp_path.suffix}"
        )
        return str(temp_path.resolve())

    def _size_limit_error(self, size_bytes: int) -> _MediaError:
        """构造超限异常，供下载与本地文件共用。"""
        return _MediaError(
            f"文件超出 {self._max_file_size_mb}MB 限制 "
            f"({format_bytes_to_mb(size_bytes)})"
        )

    @staticmethod
    def _parse_content_length(raw: str | None) -> int | None:
        """解析 Content-Length 响应头，非数字或负数时返回 None。"""
        if not raw:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.debug(f"Content-Length 非法，按未知长度处理: {raw!r}")
            return None
        return value if value >= 0 else None

    @staticmethod
    def _pick_suffix(file_type: str, content_type: str | None, name: str = "") -> str:
        """决定文件后缀。

        优先级：发送方提供的文件名后缀 → Content-Type → 类型默认后缀。
        仅接受各媒体类型白名单内的后缀，``.0`` 等平台内部标记会被忽略并回退。
        """
        allowed = DownloadManager._ALLOWED_EXTENSIONS.get(file_type)

        from_name = Path(name).suffix.lower() if name else ""
        if from_name and len(from_name) <= 8 and (not allowed or from_name in allowed):
            return from_name

        guessed: str | None = None
        if content_type:
            mime = content_type.split(";")[0].strip().lower()
            guessed = mimetypes.guess_extension(mime)
        if guessed and len(guessed) <= 8 and (not allowed or guessed in allowed):
            return guessed
        suffix = DownloadManager._EXT_FALLBACK.get(file_type, "")
        if not suffix:
            logger.warning(
                f"无法确定文件后缀: type={file_type}, content_type={content_type}"
            )
        return suffix

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

    def _relative(self, dest: Path) -> str:
        return dest.relative_to(self._store_dir).as_posix()

    def _build_store_path(
        self,
        file_type: str,
        content_hash: str = "",
        extension: str = "",
    ) -> Path:
        sub_dir = self._store_dir / file_type
        if file_type == "sticker":
            sub_dir = sub_dir / extension.lstrip(".")
        else:
            now = datetime.now()
            sub_dir = sub_dir / str(now.year) / f"{now.month:02d}"
        sub_dir.mkdir(parents=True, exist_ok=True)

        return sub_dir / f"{content_hash[:16]}{extension}"
