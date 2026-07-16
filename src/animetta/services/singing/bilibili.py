from __future__ import annotations

"""Bilibili audio downloader — yt-dlp wrapper. Extracts video title for naming."""

import asyncio
import contextlib
import hashlib
import re
from pathlib import Path

from loguru import logger


class BilibiliDownloader:
    """Download audio from Bilibili video URL using yt-dlp."""

    def __init__(self, output_dir: str = "./data/singing/downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def extract_bv_id(url: str) -> str:
        """Extract Bilibili BV number from URL."""
        m = re.search(r"BV[a-zA-Z0-9]{10}", url)
        return m.group(0) if m else ""

    @staticmethod
    def extract_au_id(url: str) -> str:
        """Extract Bilibili audio AU number from URL."""
        m = re.search(r"/au(\d+)", url)
        return m.group(1) if m else ""

    async def fetch_lyrics_lrc(self, url: str) -> str | None:
        """Fetch LRC lyrics from B站 audio API. Returns LRC string or None.

        For au (audio) URLs: directly GET the lyrics API.
        For BV (video) URLs: try to find associated audio first.
        Returns None when lyrics are unavailable (fallback to whisper).
        """

        # Try AU audio URLs first
        au_id = self.extract_au_id(url)
        if au_id:
            return await self._fetch_lyrics_by_sid(au_id)

        # For BV URLs, try to find associated audio via yt-dlp metadata
        bv_id = self.extract_bv_id(url)
        if bv_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "yt-dlp",
                    "--print",
                    "%(id)s",
                    "--print",
                    "%(extractor)s",
                    url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                # yt-dlp may give us an au ID for bilibili audio URLs
                if proc.returncode == 0 and stdout:
                    lines = stdout.decode("utf-8", errors="replace").strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        if line.startswith("au") and len(line) > 2:
                            sid = line[2:]
                            lyrics = await self._fetch_lyrics_by_sid(sid)
                            if lyrics:
                                return lyrics
            except Exception as e:
                logger.debug(f"Failed to resolve BV to AU: {e}")

        return None

    async def _fetch_lyrics_by_sid(self, sid: str) -> str | None:
        """Fetch LRC lyrics from B站 audio API by song ID."""
        import httpx

        api_url = f"https://www.bilibili.com/audio/music-service-c/web/song/lyric?sid={sid}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.get(
                    api_url,
                    headers={
                        "Referer": "https://www.bilibili.com/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0 and data.get("data"):
                        lrc = data["data"].get("lyric", "")
                        if lrc and lrc.strip():
                            logger.info(
                                f"Fetched LRC lyrics from B站 API (sid={sid}): {len(lrc)} chars"
                            )
                            return lrc
                logger.debug(
                    f"B站 lyrics API returned empty or error (sid={sid}, code={resp.status_code})"
                )
        except Exception as e:
            logger.debug(f"Failed to fetch B站 lyrics for sid={sid}: {e}")
        return None

    async def get_title(self, url: str) -> str:
        """Get video title from Bilibili URL via yt-dlp."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--get-title",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and stdout:
                return stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            logger.warning(f"Failed to get video title: {e}")
        return ""

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize string for use as filename."""
        return re.sub(r'[<>:"/\\|?*\n\r\t]', "_", name)[:60].strip()

    async def download(self, url: str) -> tuple[str, str, str]:
        """Download audio track from Bilibili URL.

        Returns:
            Tuple of (file_path, video_title, bv_id).
        """
        logger.info(f"Downloading Bilibili audio: {url}")

        bv_id = self.extract_bv_id(url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        output_path = self.output_dir / f"{url_hash}.wav"

        # Get video title (for metadata)
        title = await self.get_title(url)

        if output_path.exists():
            # Read cached title from metadata file
            meta_path = self.output_dir / f"{url_hash}.meta"
            cached_title = title
            if meta_path.exists() and not title:
                with contextlib.suppress(Exception):
                    cached_title = meta_path.read_text(encoding="utf-8").strip()
            else:
                with contextlib.suppress(Exception):
                    meta_path.write_text(title, encoding="utf-8")
            logger.info(f"Using cached download: {output_path} (title: {cached_title})")
            return str(output_path), cached_title, bv_id

        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format",
            "wav",
            "--audio-quality",
            "0",
            "-o",
            str(output_path.with_suffix("")),
            url,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                err_text = (
                    stderr.decode("utf-8", errors="replace")[:500] if stderr else "(no output)"
                )
                raise RuntimeError(f"yt-dlp failed (code {proc.returncode}): {err_text}")

            actual_path = output_path.with_suffix(".wav")
            if not actual_path.exists():
                candidates = list(self.output_dir.glob(f"{url_hash}*"))
                if candidates:
                    actual_path = candidates[0]
                else:
                    raise RuntimeError(f"Downloaded file not found for hash: {url_hash}")

            # Save title metadata
            if title:
                meta_path = self.output_dir / f"{url_hash}.meta"
                meta_path.write_text(title, encoding="utf-8")

            logger.info(f"Download complete: {actual_path} (title: {title or bv_id})")
            return str(actual_path), title, bv_id

        except FileNotFoundError:
            raise RuntimeError("yt-dlp not found. Install with: pip install yt-dlp") from None

    async def close(self) -> None:
        pass
