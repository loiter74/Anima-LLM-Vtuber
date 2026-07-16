from __future__ import annotations

"""RVC bridge via direct Python subprocess wrapper."""
import asyncio
import os
from pathlib import Path

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
    ) -> None:
        del manage_server  # Retained for compatibility; this bridge never owns the server.
        self.rvc_path = Path(rvc_path or self.DEFAULT_RVC_PATH)
        self.python_exe = python_exe or str(self.rvc_path / "runtime" / "python.exe")
        self.model_name = model_name
        self.index_path = index_path
        self.f0_method = f0_method
        self.f0_up_key = f0_up_key
        self.index_rate = index_rate
        self.filter_radius = filter_radius
        self.rms_mix_rate = rms_mix_rate
        self.protect = protect

    async def convert(
        self,
        source_audio_path: str | Path,
        output_path: str | Path,
        pitch_adjust: int = 0,
    ) -> str:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
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

    async def close(self) -> None:
        pass
