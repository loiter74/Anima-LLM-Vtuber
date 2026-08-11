"""Run the host-local RVC service with Uvicorn."""

import os

import uvicorn

from .app import create_app
from .host import build_host_service_from_env


def main() -> None:
    uvicorn.run(
        create_app(build_host_service_from_env()),
        host=os.getenv("RVC_HOST_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("RVC_HOST_BIND_PORT", "8769")),
    )


if __name__ == "__main__":
    main()
