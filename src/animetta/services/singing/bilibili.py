from __future__ import annotations

"""Bilibili audio downloader with an official API path and yt-dlp fallback."""

import asyncio
import contextlib
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from loguru import logger

_BILIBILI_API_BASE = "https://api.bilibili.com"
_BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_BILIBILI_MEDIA_HOSTS = ("bilivideo.com", "bilivideo.cn", "akamaized.net")


class BilibiliDownloader:
    """Download audio from Bilibili, preferring its public BV APIs."""

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
        """Get the video title from the public BV API, then fall back to yt-dlp."""
        bv_id = self.extract_bv_id(url)
        if bv_id:
            try:
                async with self._create_http_client() as client:
                    title, _ = await self._fetch_bv_info(client, bv_id)
                return title
            except (httpx.HTTPError, TypeError, ValueError) as error:
                logger.warning(f"Bilibili title API failed; using yt-dlp fallback: {error}")

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

    @staticmethod
    def _create_http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=False,
        )

    @staticmethod
    def _headers(bv_id: str = "") -> dict[str, str]:
        referer = "https://www.bilibili.com/"
        if bv_id:
            referer = f"https://www.bilibili.com/video/{bv_id}"
        return {"Referer": referer, "User-Agent": _BILIBILI_USER_AGENT}

    async def _fetch_bv_info(self, client: httpx.AsyncClient, bv_id: str) -> tuple[str, int]:
        response = await client.get(
            f"{_BILIBILI_API_BASE}/x/web-interface/view",
            params={"bvid": bv_id},
            headers=self._headers(bv_id),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Bilibili view API returned an invalid response")
        data = payload.get("data")
        if payload.get("code") != 0 or not isinstance(data, dict):
            raise ValueError("Bilibili view API returned an invalid response")
        title = data.get("title")
        cid = data.get("cid")
        if not isinstance(title, str) or not title.strip() or not isinstance(cid, int):
            raise ValueError("Bilibili view API omitted title or cid")
        return title.strip(), cid

    async def _fetch_audio_url(self, client: httpx.AsyncClient, bv_id: str, cid: int) -> str:
        response = await client.get(
            f"{_BILIBILI_API_BASE}/x/player/playurl",
            params={"bvid": bv_id, "cid": cid, "fnval": 16, "fourk": 0},
            headers=self._headers(bv_id),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Bilibili playurl API returned no DASH audio")
        data = payload.get("data")
        dash = data.get("dash") if isinstance(data, dict) else None
        audio_tracks = dash.get("audio") if isinstance(dash, dict) else None
        if payload.get("code") != 0 or not isinstance(audio_tracks, list) or not audio_tracks:
            raise ValueError("Bilibili playurl API returned no DASH audio")
        track = max(
            (item for item in audio_tracks if isinstance(item, dict)),
            key=lambda item: int(item.get("bandwidth") or 0),
            default=None,
        )
        audio_url = (track or {}).get("baseUrl") or (track or {}).get("base_url")
        if not isinstance(audio_url, str) or not self._is_allowed_media_url(audio_url):
            raise ValueError("Bilibili playurl API returned an unsupported media URL")
        return audio_url

    @staticmethod
    def _is_allowed_media_url(url: str) -> bool:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(
            host == suffix or host.endswith(f".{suffix}") for suffix in _BILIBILI_MEDIA_HOSTS
        )

    async def _download_bv_via_api(self, bv_id: str, output_path: Path) -> tuple[str, Path]:
        source_path = output_path.with_suffix(".m4s.part")
        source_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        try:
            async with self._create_http_client() as client:
                title, cid = await self._fetch_bv_info(client, bv_id)
                audio_url = await self._fetch_audio_url(client, bv_id, cid)
                async with client.stream(
                    "GET", audio_url, headers=self._headers(bv_id)
                ) as response:
                    response.raise_for_status()
                    with source_path.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
            if not source_path.exists() or source_path.stat().st_size == 0:
                raise RuntimeError("Bilibili CDN returned an empty audio stream")
            await self._convert_to_wav(source_path, output_path)
            return title, output_path
        finally:
            source_path.unlink(missing_ok=True)

    @staticmethod
    async def _convert_to_wav(source_path: Path, output_path: Path) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found; it is required for Bilibili audio") from None
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output_path.exists():
            output_path.unlink(missing_ok=True)
            error = stderr.decode("utf-8", errors="replace")[:500] if stderr else "(no output)"
            raise RuntimeError(f"ffmpeg failed to decode Bilibili audio: {error}")

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

        if output_path.exists():
            # Read cached title from metadata file
            meta_path = self.output_dir / f"{url_hash}.meta"
            cached_title = ""
            if meta_path.exists():
                with contextlib.suppress(Exception):
                    cached_title = meta_path.read_text(encoding="utf-8").strip()
            if not cached_title:
                cached_title = await self.get_title(url)
            logger.info(f"Using cached download: {output_path} (title: {cached_title})")
            return str(output_path), cached_title, bv_id

        if bv_id:
            try:
                title, actual_path = await self._download_bv_via_api(bv_id, output_path)
                meta_path = self.output_dir / f"{url_hash}.meta"
                meta_path.write_text(title, encoding="utf-8")
                logger.info(f"Download complete via Bilibili API: {actual_path} (title: {title})")
                return str(actual_path), title, bv_id
            except (httpx.HTTPError, TypeError, ValueError, RuntimeError) as error:
                logger.warning(f"Bilibili API download failed; using yt-dlp fallback: {error}")

        title = await self.get_title(url)

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
