#!/usr/bin/env python3
"""Run Demucs while saving WAV stems through soundfile instead of TorchCodec."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio


def _soundfile_save(
    uri: str | Path,
    source: torch.Tensor,
    sample_rate: int,
    **_kwargs: object,
) -> None:
    """Implement the small torchaudio.save surface used by Demucs."""

    array = source.detach().cpu().numpy()
    if array.ndim == 2:
        array = array.T
    sf.write(str(uri), np.asarray(array, dtype=np.float32), sample_rate, subtype="PCM_16")


torchaudio.save = _soundfile_save

import demucs.audio as demucs_audio  # noqa: E402


def _save_audio(
    wav: object,
    path: str | Path,
    samplerate: int,
    bitrate: int = 320,
    clip: str = "rescale",
    bits_per_sample: int = 16,
    as_float: bool = False,
    preset: int = 2,
) -> None:
    """Match Demucs save semantics without importing TorchCodec."""

    del bitrate, preset
    prepared = demucs_audio.prevent_clip(wav, mode=clip)
    array = prepared.detach().cpu().numpy()
    if array.ndim == 2:
        array = array.T
    subtype = "FLOAT" if as_float else {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}[bits_per_sample]
    sf.write(str(path), np.asarray(array, dtype=np.float32), samplerate, subtype=subtype)


demucs_audio.save_audio = _save_audio

from demucs.separate import main as demucs_main  # noqa: E402

if __name__ == "__main__":
    demucs_main()
