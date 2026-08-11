# Reference voice assets

## Active local host reference

The active Windows-host Qwen voice uses a local-only reference and is not
copied into the repository. Voice identity, reference path, transcript and
SHA-256 live together in `config/host-tts.yaml`. Replace that one contract and
rerun the standard host-TTS lifecycle; no source or test literals need editing.

## `animetta-vivian-reference.wav`

This is synthetic speech generated locally with the official
`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` model and its built-in `Vivian` speaker.
It does not contain a recording copied from a real person, performer, game,
anime, film, or livestream.

- Transcript: `你好，我是千问，你今天过得好吗？`
- Format: 24 kHz, mono, signed 16-bit PCM WAV
- Duration: 3.28 seconds
- SHA-256: `A2BBFF2BB0E33C72027DC0BB24565FA288BDF81FD147172861A3BC8831412E73`
- Generator: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- Generator/model license: [Apache License 2.0](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE)

The short transcript was generated for this reference clip and may be reused
with the audio. Keep its hash and transcript together if this file is selected
in `config/host-tts.yaml`.
