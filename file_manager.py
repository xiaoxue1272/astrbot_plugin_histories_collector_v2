import hashlib
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from data.plugins.astrbot_plugin_histories_collector_v2.utils import (
    format_bytes_to_mb,
    get_http_session,
    get_plugin_data_dir,
    is_http_url,
)


class FileManager:
    """Media file download and cache manager.

    Downloads files from URLs, caches them with content-hash deduplication,
    and organizes by type and date in the plugin data directory.
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

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_mb * 1024 * 1024

    # ── Hash / path helpers ──

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
        return FileManager._EXT_FALLBACK.get(file_type, "")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove characters unsafe for filesystem paths."""
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

    # ── Download & cache ──

    async def download(
        self,
        url: str,
        file_type: str,
        file_name: str = "",
    ) -> tuple[str | None, str | None]:
        """Download a file from URL and cache it, returning (relative_path, warning).

        Args:
            url: File URL (HTTP/HTTPS or local path).
            file_type: One of "image", "sticker", "video", "voice", "file".
            file_name: Original file name (used for File type).

        Returns:
            (relative_path or None, warning message or None).
        """
        if not is_http_url(url):
            logger.warning(f"Not an HTTP URL, skipping: {url[:80]}")
            return None, f"Not a valid download URL"

        # Size pre-check
        try:
            async with (await get_http_session()).get(url, timeout=10) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_file_size_bytes:
                    logger.info(f"File exceeds size limit ({content_length} bytes), skipped: {url[:80]}")
                    return None, f"File exceeds {self._max_file_size_mb}MB limit ({format_bytes_to_mb(int(content_length))})"
        except Exception:
            pass  # Pre-check failed, proceed with download anyway

        try:
            async with (await get_http_session()).get(url, timeout=30) as resp:
                if resp.status != 200:
                    logger.warning(f"Download failed: HTTP {resp.status}, url={url[:80]}")
                    return None, "Download failed"
                suffix = self._guess_suffix(url)
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        f.write(chunk)
                    return self._cache(f.name, file_type, file_name)
        except Exception as e:
            logger.warning(f"Download failed: {e}, url={url[:80]}")
            return None, "Download failed"

    def _cache(
        self,
        temp_path: str,
        file_type: str,
        file_name: str = "",
    ) -> tuple[str | None, str | None]:
        """Cache a local file, returning (relative_path, warning)."""
        file_bytes = Path(temp_path).stat().st_size
        if file_bytes > self.max_file_size_bytes:
            self._cleanup_temp(temp_path)
            logger.info(f"File exceeds size limit ({file_bytes} bytes), skipped: {temp_path}")
            return None, f"File exceeds {self._max_file_size_mb}MB limit ({format_bytes_to_mb(file_bytes)})"

        # File type with name: use name-based path (no hashing)
        if file_type == "file" and file_name:
            dest = self._build_store_path(file_type, file_name=file_name)
            if dest.exists():
                logger.debug(f"File cache hit: {dest}")
                self._cleanup_temp(temp_path)
                return dest.relative_to(self._store_dir).as_posix(), None
            shutil.copy(temp_path, dest)
            logger.debug(f"File cached: {dest}")
            self._cleanup_temp(temp_path)
            return dest.relative_to(self._store_dir).as_posix(), None

        md5_hash = self._compute_hash(temp_path, "md5")
        extension = self._extract_extension(temp_path, file_type)
        dest = self._build_store_path(file_type, md5_hash, extension)

        if dest.exists():
            new_sha256 = self._compute_hash(temp_path, "sha256")
            existing_sha256 = self._compute_hash(str(dest), "sha256")
            if new_sha256 == existing_sha256:
                logger.debug(f"File cache hit: {dest}")
                self._cleanup_temp(temp_path)
                return dest.relative_to(self._store_dir).as_posix(), None
            logger.warning(f"MD5 collision: {temp_path}, using SHA-256 name")
            dest = self._build_store_path(file_type, new_sha256, extension)
            if dest.exists():
                logger.debug(f"File cache hit (SHA-256): {dest}")
                self._cleanup_temp(temp_path)
                return dest.relative_to(self._store_dir).as_posix(), None

        shutil.copy(temp_path, dest)
        logger.debug(f"File cached: {dest}")
        self._cleanup_temp(temp_path)
        return dest.relative_to(self._store_dir).as_posix(), None

    @staticmethod
    def _guess_suffix(url: str) -> str:
        """Guess file extension from URL path."""
        suffix = Path(url.split("?")[0]).suffix
        return suffix if suffix and len(suffix) <= 8 else ""

    @staticmethod
    def _cleanup_temp(temp_path: str) -> None:
        """Delete the downloaded temporary file."""
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
