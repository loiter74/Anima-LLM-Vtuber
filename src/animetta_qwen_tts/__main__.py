"""Run the host-local GGUF Qwen TTS service with Uvicorn."""

import os

import uvicorn

from .app import create_app
from .gguf_host import build_host_service_from_env


def main() -> None:
    uvicorn.run(
        create_app(service=build_host_service_from_env()),
        host=os.getenv("QWEN_TTS_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("QWEN_TTS_BIND_PORT", "8767")),
    )


if __name__ == "__main__":
    main()
