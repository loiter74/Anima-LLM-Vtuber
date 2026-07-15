"""Run the independent Qwen TTS service with Uvicorn."""

import os

import uvicorn

from .app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.getenv("QWEN_TTS_BIND_HOST", "0.0.0.0"),
        port=int(os.getenv("QWEN_TTS_BIND_PORT", "8766")),
    )


if __name__ == "__main__":
    main()
