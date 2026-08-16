"""Host wrapper for account recovery in Animetta's named data volume."""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys

PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Animetta 用户恢复工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reset = subparsers.add_parser("reset-admin-password", help="重置管理员临时密码")
    reset.add_argument("--username", required=True)
    reset.add_argument("--enable", action="store_true", help="同时恢复已禁用的管理员")
    return parser


def main() -> int:
    args = _parser().parse_args()
    password = getpass.getpass("新临时密码：")
    confirmation = getpass.getpass("再次输入：")
    if password != confirmation:
        print("两次输入的密码不一致。", file=sys.stderr)
        return 2
    password_bytes = len(password.encode("utf-8"))
    if not PASSWORD_MIN_BYTES <= password_bytes <= PASSWORD_MAX_BYTES:
        print("密码必须为 8–1024 个 UTF-8 字节。", file=sys.stderr)
        return 2
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "animetta",
        "python",
        "-m",
        "animetta.orchestration.server.auth_admin_cli",
        "reset-admin-password",
        "--username",
        str(args.username),
    ]
    if args.enable:
        command.append("--enable")
    try:
        completed = subprocess.run(
            command,
            input=password + "\n",
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("Docker 不可用；请先安装或启动 Docker Desktop。", file=sys.stderr)
        return 3
    if completed.returncode != 0:
        print(
            "管理员恢复失败；请先通过 runtime_lifecycle.py anima-up 启动 Animetta。",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
