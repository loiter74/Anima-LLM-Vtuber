# 手写 SVG 规范

SVG 是逃生舱——只在 Mermaid 和 Canvas 都无法满足时使用。

## 何时用 SVG

- 像素级定制的视觉效果
- 插画 / 图标
- Mermaid 无法表达的精确布局
- 需要嵌入特定样式的场景

**判据**: 先问"Mermaid 能画吗?" → 能就用 Mermaid。再问"Canvas 能摆吗?" → 能就用 Canvas。都不行 → 才用 SVG。

## 设计规范

### 命名空间

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">
  <!-- 内容 -->
</svg>
```

### 颜色语义

与 Mermaid/Canvas 保持一致:

| 语义 | 颜色值 |
|------|--------|
| 中性/复用 | `#f0f0f0` / `#999` |
| 扩展 | `#e0f7fa` / `#00bcd4` |
| 新建/成功 | `#e8f5e9` / `#4caf50` |
| 失败/删除 | `#ffebee` / `#f44336` |
| 判断/分支 | `#fff8e1` / `#ffc107` |
| 安全层 | `#f3e5f5` / `#9c27b0` |

### 尺寸规范

```xml
<!-- 步骤节点: 240x64 -->
<rect x="0" y="0" width="240" height="64" rx="8" fill="#e0f7fa" stroke="#00bcd4"/>

<!-- 判断节点: 200x56 -->
<rect x="0" y="0" width="200" height="56" rx="8" fill="#fff8e1" stroke="#ffc107"/>

<!-- 文字: 垂直居中 -->
<text x="120" y="36" text-anchor="middle" dominant-baseline="middle" font-size="14">
  <tspan font-weight="bold">标题</tspan>
  <tspan x="120" dy="20" font-size="12" fill="#666">描述</tspan>
</text>
```

### 网格对齐

```xml
<!-- 列1: x=0 -->
<rect x="0" y="0" .../>

<!-- 列2: x=300 -->
<rect x="300" y="0" .../>

<!-- 行距: 96px -->
<rect x="0" y="0" .../>
<rect x="0" y="96" .../>
```

## 预检清单

产出 SVG 前,逐项检查:

- [ ] 节点标题用 `<tspan font-weight="bold">`,不用 `<h1>` / `<h2>`
- [ ] 颜色来自固定 6 色映射,不是随机
- [ ] 同角色节点尺寸一致
- [ ] 同列共用 x,行距统一
- [ ] 文字垂直居中 (`dominant-baseline="middle"`)
- [ ] 圆角统一 (`rx="8"`)
- [ ] 边有箭头标记
- [ ] viewBox 设置正确

## 完整示例

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#999"/>
    </marker>
  </defs>
  
  <!-- 步骤1 -->
  <rect x="0" y="0" width="240" height="64" rx="8" fill="#e0f7fa" stroke="#00bcd4"/>
  <text x="120" y="36" text-anchor="middle" dominant-baseline="middle" font-size="14">
    <tspan font-weight="bold">① 课程提议</tspan>
    <tspan x="120" dy="20" font-size="12" fill="#666">llm-planner</tspan>
  </text>
  
  <!-- 步骤2 -->
  <rect x="300" y="0" width="240" height="64" rx="8" fill="#e8f5e9" stroke="#4caf50"/>
  <text x="420" y="36" text-anchor="middle" dominant-baseline="middle" font-size="14">
    <tspan font-weight="bold">② 技能检索</tspan>
    <tspan x="420" dy="20" font-size="12" fill="#666">skill-library</tspan>
  </text>
  
  <!-- 边 -->
  <line x1="240" y1="32" x2="300" y2="32" stroke="#999" marker-end="url(#arrow)"/>
  <text x="270" y="24" text-anchor="middle" font-size="12" fill="#666">调用</text>
</svg>
```

## 嵌入 Obsidian

### 内联 SVG

在 Markdown 中直接写 `<svg>`:

```markdown
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300">
  <!-- 内容 -->
</svg>
```

### 外部 SVG 文件

```markdown
![[diagram.svg]]
```

## 常见错误

| 错误 | 后果 | 正确做法 |
|------|------|---------|
| 用 `<h1>` / `<h2>` | 渲染成巨号字 | 用 `<tspan font-weight="bold">` |
| 颜色随机 | 视觉噪声 | 固定 6 色语义 |
| 尺寸不一 | 列对不齐 | 同角色同尺寸 |
| 没有 viewBox | 缩放异常 | 设置 viewBox |
| 没有箭头标记 | 边无方向 | 用 `<marker>` 定义箭头 |
| 文字没居中 | 偏移 | `text-anchor="middle"` + `dominant-baseline="middle"` |
