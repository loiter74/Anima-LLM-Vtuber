#!/usr/bin/env python3
"""
验证 Socket.IO 事件名一致性

此脚本检查：
1. config/socket-events.json 中定义的事件名是否与后端 routes.py 中的注册一致
2. 前端代码中使用的事件名是否与 JSON 定义一致

用法：
    python scripts/validate-events.py

退出码：
    0 - 验证通过
    1 - 验证失败
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent

# 文件路径
JSON_PATH = ROOT_DIR / "config" / "socket-events.json"
ROUTES_PY = ROOT_DIR / "src" / "animetta" / "orchestration" / "server" / "routes.py"
FRONTEND_DIR = ROOT_DIR / "frontend" / "src"


def load_json_events() -> dict[str, str]:
    """从 JSON 文件加载所有事件名，返回 {事件名: 模块名} 映射"""
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    events = {}
    for module_name, module_events in data.items():
        for event_key, event_config in module_events.items():
            event_name = event_config["name"]
            events[event_name] = module_name

    return events


def extract_routes_py_events() -> set[str]:
    """从 routes.py 中提取所有 sio.on() 注册的事件名"""
    with open(ROUTES_PY, encoding="utf-8") as f:
        content = f.read()

    # 匹配 sio.on("event_name", ...) 模式
    pattern = r'sio\.on\(["\']([^"\']+)["\']'
    return set(re.findall(pattern, content))


def extract_frontend_emit_events() -> set[str]:
    """从前端代码中提取所有 socket.emit() 调用的事件名"""
    events = set()

    # 匹配 socket.emit("event_name", ...) 模式
    pattern = r'socket\.emit\(["\']([^"\']+)["\']'

    for ts_file in FRONTEND_DIR.rglob("*.ts"):
        with open(ts_file, encoding="utf-8") as f:
            content = f.read()
            events.update(re.findall(pattern, content))

    for vue_file in FRONTEND_DIR.rglob("*.vue"):
        with open(vue_file, encoding="utf-8") as f:
            content = f.read()
            events.update(re.findall(pattern, content))

    return events


def extract_frontend_on_events() -> set[str]:
    """从前端代码中提取所有 socket.on() 监听的事件名"""
    events = set()

    # 匹配 socket.on("event_name", ...) 模式
    pattern = r'socket\.on\(["\']([^"\']+)["\']'

    for ts_file in FRONTEND_DIR.rglob("*.ts"):
        with open(ts_file, encoding="utf-8") as f:
            content = f.read()
            events.update(re.findall(pattern, content))

    for vue_file in FRONTEND_DIR.rglob("*.vue"):
        with open(vue_file, encoding="utf-8") as f:
            content = f.read()
            events.update(re.findall(pattern, content))

    return events


def validate_json_format(events: dict[str, str]) -> list[str]:
    """验证 JSON 格式是否正确"""
    errors = []

    for event_name, module_name in events.items():
        # 检查是否使用点分隔
        if "." not in event_name:
            errors.append(f"事件 '{event_name}' 未使用点分隔格式")

        # 检查模块名是否匹配
        expected_module = event_name.split(".")[0]
        if module_name != expected_module:
            errors.append(
                f"事件 '{event_name}' 的模块名 '{module_name}' 与预期 '{expected_module}' 不匹配"
            )

    return errors


def validate_routes_py_consistency(
    json_events: dict[str, str], routes_events: set[str]
) -> list[str]:
    """验证 routes.py 中的事件名与 JSON 定义一致"""
    errors = []

    # 获取 JSON 中的所有事件名
    json_event_names = set(json_events.keys())

    # 检查 routes.py 中是否有 JSON 中不存在的事件
    missing_in_json = routes_events - json_event_names
    if missing_in_json:
        errors.append(f"routes.py 中有 JSON 中不存在的事件: {missing_in_json}")

    # 检查 JSON 中是否有 routes.py 中未注册的事件
    missing_in_routes = json_event_names - routes_events
    if missing_in_routes:
        errors.append(f"JSON 中有 routes.py 中未注册的事件: {missing_in_routes}")

    return errors


def validate_frontend_consistency(
    json_events: dict[str, str],
    emit_events: set[str],
    on_events: set[str],
) -> list[str]:
    """验证前端代码中的事件名与 JSON 定义一致"""
    errors = []

    json_event_names = set(json_events.keys())

    # 过滤掉 socket.io 内置事件
    builtin_events = {"connect", "disconnect", "connect_error"}
    emit_events = emit_events - builtin_events
    on_events = on_events - builtin_events

    # 检查 emit 中是否有 JSON 中不存在的事件
    missing_in_json = emit_events - json_event_names
    if missing_in_json:
        errors.append(f"前端 emit 中有 JSON 中不存在的事件: {missing_in_json}")

    # 检查 on 中是否有 JSON 中不存在的事件
    missing_in_json = on_events - json_event_names
    if missing_in_json:
        errors.append(f"前端 on 中有 JSON 中不存在的事件: {missing_in_json}")

    return errors


def check_old_event_names(emit_events: set[str], on_events: set[str]) -> list[str]:
    """检查是否还有使用旧事件名的代码"""
    errors = []

    # 定义旧事件名模式
    old_patterns = [
        # 下划线格式（排除合法的新格式）
        r"^[a-z]+_[a-z]+",
        # 冒号格式
        r"^[a-z]+:[a-z]+",
    ]

    all_events = emit_events | on_events

    for event in all_events:
        # 跳过 socket.io 内置事件
        if event in {"connect", "disconnect", "connect_error"}:
            continue

        # 检查是否匹配旧格式
        for pattern in old_patterns:
            if re.match(pattern, event):
                errors.append(f"发现旧格式事件名: '{event}'，请迁移到点分隔格式")
                break

    return errors


def main() -> int:
    """主函数"""
    print("=" * 60)
    print("Socket.IO 事件名一致性验证")
    print("=" * 60)

    all_errors: list[str] = []

    # 1. 加载 JSON 事件
    print("\n[1/5] 加载 JSON 事件定义...")
    try:
        json_events = load_json_events()
        print(f"  ✓ 加载了 {len(json_events)} 个事件")
    except Exception as e:
        print(f"  ✗ 加载失败: {e}")
        return 1

    # 2. 验证 JSON 格式
    print("\n[2/5] 验证 JSON 格式...")
    format_errors = validate_json_format(json_events)
    if format_errors:
        all_errors.extend(format_errors)
        print(f"  ✗ 发现 {len(format_errors)} 个格式错误")
    else:
        print("  ✓ JSON 格式正确")

    # 3. 验证 routes.py 一致性
    print("\n[3/5] 验证 routes.py 一致性...")
    try:
        routes_events = extract_routes_py_events()
        print(f"  ✓ 从 routes.py 提取了 {len(routes_events)} 个事件")

        routes_errors = validate_routes_py_consistency(json_events, routes_events)
        if routes_errors:
            all_errors.extend(routes_errors)
            print(f"  ✗ 发现 {len(routes_errors)} 个不一致")
        else:
            print("  ✓ routes.py 与 JSON 一致")
    except Exception as e:
        print(f"  ✗ 验证失败: {e}")
        all_errors.append(f"routes.py 验证失败: {e}")

    # 4. 验证前端一致性
    print("\n[4/5] 验证前端一致性...")
    try:
        emit_events = extract_frontend_emit_events()
        on_events = extract_frontend_on_events()
        print(f"  ✓ 从前端提取了 {len(emit_events)} 个 emit 事件, {len(on_events)} 个 on 事件")

        frontend_errors = validate_frontend_consistency(
            json_events, emit_events, on_events
        )
        if frontend_errors:
            all_errors.extend(frontend_errors)
            print(f"  ✗ 发现 {len(frontend_errors)} 个不一致")
        else:
            print("  ✓ 前端与 JSON 一致")
    except Exception as e:
        print(f"  ✗ 验证失败: {e}")
        all_errors.append(f"前端验证失败: {e}")

    # 5. 检查旧事件名
    print("\n[5/5] 检查旧事件名...")
    try:
        old_name_errors = check_old_event_names(emit_events, on_events)
        if old_name_errors:
            all_errors.extend(old_name_errors)
            print(f"  ✗ 发现 {len(old_name_errors)} 个旧格式事件名")
        else:
            print("  ✓ 未发现旧格式事件名")
    except Exception as e:
        print(f"  ✗ 检查失败: {e}")
        all_errors.append(f"旧事件名检查失败: {e}")

    # 输出结果
    print("\n" + "=" * 60)
    if all_errors:
        print(f"验证失败: 发现 {len(all_errors)} 个错误")
        print("=" * 60)
        for i, error in enumerate(all_errors, 1):
            print(f"{i}. {error}")
        print("=" * 60)
        return 1
    else:
        print("验证通过: 所有事件名一致")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())
