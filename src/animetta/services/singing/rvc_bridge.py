from __future__ import annotations

"""RVC bridge via direct Python subprocess wrapper."""
import asyncio
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from loguru import logger


class RVCBridge:
    DEFAULT_RVC_PATH = r"C:\Users\30262\RVC20240604Nvidia"

    def __init__(
        self,
        rvc_path: str | Path = "",
        python_exe: str | Path = "",
        model_name: str = "kikiV1.pth",
        index_path: str | Path = "logs/kikiV1.index",
        f0_method: str = "rmvpe",
        f0_up_key: int = 0,
        index_rate: float = 0.75,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
        manage_server: bool = False,
        base_url: str = "",
        api_key: str = "",
        expected_revision: str = "",
        request_timeout_seconds: float = 1200.0,
    ) -> None:
        del manage_server  # Retained for compatibility; this bridge never owns the server.
        self.rvc_path = Path(rvc_path or self.DEFAULT_RVC_PATH)
        bundled_python = self.rvc_path / "runtime" / "Scripts" / "python.exe"
        self.python_exe = python_exe or str(
            bundled_python if bundled_python.is_file() else Path(sys.executable)
        )
        self.model_name = model_name
        self.index_path = index_path
        self.f0_method = f0_method
        self.f0_up_key = f0_up_key
        self.index_rate = index_rate
        self.filter_radius = filter_radius
        self.rms_mix_rate = rms_mix_rate
        self.protect = protect
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.expected_revision = expected_revision
        self.request_timeout_seconds = request_timeout_seconds
        self.last_identity: dict[str, str] = {}

    async def convert(
        self,
        source_audio_path: str | Path,
        output_path: str | Path,
        pitch_adjust: int = 0,
    ) -> str:
        problems = self.availability_problems()
        if problems:
            raise RuntimeError("RVC unavailable: " + "; ".join(problems))
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.base_url:
            payload = {
                "model": self.model_name,
                "audio_base64": base64.b64encode(Path(source_audio_path).read_bytes()).decode(
                    "ascii"
                ),
                "f0_up_key": pitch_adjust or self.f0_up_key,
                "f0_method": self.f0_method,
                "index_rate": self.index_rate,
                "filter_radius": self.filter_radius,
                "rms_mix_rate": self.rms_mix_rate,
                "protect": self.protect,
            }
            audio, headers = await asyncio.to_thread(self._request_remote, payload)
            identity = {
                "provider": headers.get("x-rvc-provider", ""),
                "model": headers.get("x-rvc-model", ""),
                "revision": headers.get("x-rvc-revision", ""),
                "voice": headers.get("x-rvc-voice", ""),
            }
            if identity["model"] != self.model_name:
                raise RuntimeError("RVC host model identity mismatch")
            if self.expected_revision and identity["revision"] != self.expected_revision:
                raise RuntimeError("RVC host revision identity mismatch")
            if len(audio) <= 44:
                raise RuntimeError("RVC host returned empty audio")
            actual = out.with_suffix(".wav")
            actual.write_bytes(audio)
            self.last_identity = identity
            logger.info(
                f"RVC host done: {actual} provider={identity['provider']} "
                f"model={identity['model']} revision={identity['revision']}"
            )
            return str(actual)
        wrapper = self.rvc_path / "tools" / "rvc_convert_wrapper.py"
        cmd = [
            self.python_exe,
            str(wrapper),
            "--input_path",
            os.path.abspath(source_audio_path),
            "--output_path",
            os.path.abspath(str(out.with_suffix(".wav"))),
            "--model_name",
            self.model_name,
            "--index_path",
            self.index_path,
            "--f0_up_key",
            str(pitch_adjust or self.f0_up_key),
            "--f0method",
            self.f0_method,
            "--index_rate",
            str(self.index_rate),
            "--filter_radius",
            str(self.filter_radius),
            "--rms_mix_rate",
            str(self.rms_mix_rate),
            "--protect",
            str(self.protect),
        ]
        logger.info(f"RVC: {source_audio_path} model={self.model_name}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        model_root = self._model_root()
        env.setdefault("weight_root", str(model_root))
        env.setdefault("index_root", str(self.rvc_path / "logs"))
        env.setdefault("rmvpe_root", str(self.rvc_path / "assets" / "rmvpe"))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.rvc_path),
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1200)
        if proc.returncode != 0:
            raise RuntimeError(f"RVC failed: {stderr.decode('utf-8', 'replace')[:1500]}")
        actual = out.with_suffix(".wav")
        if actual.exists() and actual.stat().st_size > 1000:
            logger.info(f"RVC done: {actual}")
            return str(actual)
        raise RuntimeError(f"RVC output not found: {actual}")

    def _request_remote(self, payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
        headers = {"Content-Type": "application/json", "Accept": "audio/wav"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/v1/convert",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured local host service
                request,
                timeout=self.request_timeout_seconds,
            ) as response:
                audio = response.read()
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"RVC host HTTP {exc.code}: {detail}") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ConnectionError(f"RVC host unavailable: {exc}") from exc
        return audio, response_headers

    def _model_root(self) -> Path:
        candidates = (self.rvc_path / "assets" / "weights", self.rvc_path / "weights")
        return next(
            (path for path in candidates if (path / self.model_name).is_file()), candidates[0]
        )

    @property
    def model_path(self) -> Path:
        return self._model_root() / self.model_name

    def availability_problems(self) -> list[str]:
        problems: list[str] = []
        if self.base_url:
            if not self.base_url.startswith(("http://", "https://")):
                problems.append("remote base URL is invalid")
            if not self.api_key:
                problems.append("remote API key missing")
            return problems
        if not self.rvc_path.is_dir():
            problems.append(f"runtime path missing: {self.rvc_path}")
        if not Path(self.python_exe).is_file():
            problems.append(f"python missing: {self.python_exe}")
        if not (self.rvc_path / "tools" / "rvc_convert_wrapper.py").is_file():
            problems.append("conversion wrapper missing")
        if not self.model_path.is_file():
            problems.append(f"model missing: {self.model_name}")
        return problems

    async def close(self) -> None:
        pass
