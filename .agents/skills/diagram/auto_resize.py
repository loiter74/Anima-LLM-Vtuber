#!/usr/bin/env python3
"""
Obsidian Canvas 节点尺寸自动修正 + 碰撞检测脚本

用法:
    python auto_resize.py input.canvas [output.canvas]

功能:
    - 根据文本内容自动计算节点尺寸
    - 采用"大框策略",宁可留白,不允许文字溢出
    - 检测并修正节点重叠
    - 确保 Group 包含所有子节点
    - 调整 Group 之间的间距
"""

import json
import sys
from pathlib import Path


def count_lines(text: str) -> int:
    """计算文本行数"""
    return text.count("\n") + 1


def calc_width(text: str) -> int:
    """计算节点宽度"""
    # 中文字符按 2 个字符宽度计算
    char_count = 0
    for ch in text:
        if ord(ch) > 0x7F:
            char_count += 2
        else:
            char_count += 1
    return max(180, char_count * 3)


def calc_height(text: str) -> int:
    """计算节点高度"""
    lines = count_lines(text)
    return 60 + lines * 20


def resize_node(node: dict) -> dict:
    """调整单个节点尺寸"""
    if node.get("type") == "text":
        text = node.get("text", "")
        if text:
            new_width = calc_width(text)
            new_height = calc_height(text)
            node["width"] = max(node.get("width", 0), new_width)
            node["height"] = max(node.get("height", 0), new_height)
    return node


def get_bbox(node: dict) -> tuple:
    """获取节点边界框 (x, y, width, height)"""
    return (
        node.get("x", 0),
        node.get("y", 0),
        node.get("width", 0),
        node.get("height", 0)
    )


def bbox_overlap(bbox1: tuple, bbox2: tuple) -> bool:
    """检查两个边界框是否重叠"""
    x1, y1, w1, h1 = bbox1
    x2, y2, w2, h2 = bbox2
    
    if x1 + w1 <= x2 or x2 + w2 <= x1:
        return False
    if y1 + h1 <= y2 or y2 + h2 <= y1:
        return False
    return True


def get_children(group: dict, nodes: list) -> list:
    """获取 Group 内部的子节点"""
    gx, gy, gw, gh = get_bbox(group)
    children = []
    for node in nodes:
        if node.get("type") == "group":
            continue
        nx, ny, nw, nh = get_bbox(node)
        cx, cy = nx + nw / 2, ny + nh / 2
        if gx <= cx <= gx + gw and gy <= cy <= gy + gh:
            children.append(node)
    return children


def resize_canvas(input_path: str, output_path: str = None) -> None:
    """调整 Canvas 文件中所有节点的尺寸并修复重叠"""
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path
    else:
        output_path = Path(output_path)
    
    # 读取 Canvas
    with open(input_path, "r", encoding="utf-8") as f:
        canvas = json.load(f)
    
    nodes = canvas.get("nodes", [])
    
    # 1. 调整 text 节点尺寸
    resized_count = 0
    for i, node in enumerate(nodes):
        old_width = node.get("width", 0)
        old_height = node.get("height", 0)
        nodes[i] = resize_node(node)
        if nodes[i]["width"] != old_width or nodes[i]["height"] != old_height:
            resized_count += 1
    
    # 2. 调整 Group 尺寸，确保包含所有子节点
    groups = [n for n in nodes if n.get("type") == "group"]
    for group in groups:
        children = get_children(group, nodes)
        if not children:
            continue
        
        # 计算包含所有子节点所需的最小边界
        min_x = min(n["x"] for n in children)
        min_y = min(n["y"] for n in children)
        max_x = max(n["x"] + n["width"] for n in children)
        max_y = max(n["y"] + n["height"] for n in children)
        
        # 添加 padding
        padding = 40
        required_x = min_x - padding
        required_y = min_y - padding
        required_w = max_x - min_x + 2 * padding
        required_h = max_y - min_y + 2 * padding
        
        # 调整 Group 尺寸
        group["width"] = max(group["width"], required_w)
        group["height"] = max(group["height"], required_h)
    
    # 3. 调整 Group 位置，确保不重叠
    groups.sort(key=lambda g: (g.get("y", 0), g.get("x", 0)))
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            bbox_i = get_bbox(groups[i])
            bbox_j = get_bbox(groups[j])
            
            if bbox_overlap(bbox_i, bbox_j):
                x_i, y_i, w_i, h_i = bbox_i
                # 向下移动
                groups[j]["y"] = y_i + h_i + 50
    
    # 4. 调整非 Group 节点位置，确保不重叠
    non_groups = [n for n in nodes if n.get("type") != "group"]
    non_groups.sort(key=lambda n: (n.get("y", 0), n.get("x", 0)))
    
    for i in range(len(non_groups)):
        for j in range(i + 1, len(non_groups)):
            bbox_i = get_bbox(non_groups[i])
            bbox_j = get_bbox(non_groups[j])
            
            if bbox_overlap(bbox_i, bbox_j):
                x_i, y_i, w_i, h_i = bbox_i
                # 向下移动
                non_groups[j]["y"] = y_i + h_i + 30
    
    canvas["nodes"] = nodes
    
    # 写入 Canvas
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(canvas, f, indent=2, ensure_ascii=False)
    
    print(f"[OK] Resized {resized_count}/{len(nodes)} nodes")
    print(f"[OUT] {output_path}")


def main():
    if len(sys.argv) < 2:
        print("用法: python auto_resize.py input.canvas [output.canvas]")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    resize_canvas(input_path, output_path)


if __name__ == "__main__":
    main()
