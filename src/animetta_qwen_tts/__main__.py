"""Run the independent Qwen TTS service with Uvicorn."""

import os

import uvicorn

from .app import create_app


def main() -> None:
    engine_kind = os.getenv("QWEN_TTS_ENGINE", "manifest")
    service = None
    default_port = "8766"
    if engine_kind == "gguf-host":
        from .gguf_host import build_host_service_from_env

        service = build_host_service_from_env()
        default_port = "8767"
    uvicorn.run(
        create_app(service=service),
        host=os.getenv("QWEN_TTS_BIND_HOST", "0.0.0.0"),
        port=int(os.getenv("QWEN_TTS_BIND_PORT", default_port)),
    )


if __name__ == "__main__":
    main()
