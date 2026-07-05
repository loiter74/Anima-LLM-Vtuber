# danmaku-buffer Specification

## Purpose
TBD - created by archiving change improve-danmaku-meme-collection. Update Purpose after archive.
## Requirements
### Requirement: 实时弹幕接收
系统 SHALL 从 `BilibiliDanmakuService` 接收实时弹幕消息并存入内存缓冲区。

#### Scenario: 弹幕推入缓冲区
- **WHEN** `BilibiliDanmakuService._consume_queue` 消费到一条 `DANMU_MSG` 事件
- **THEN** 系统 SHALL 将弹幕文本推入 `DanmakuBuffer`
- **AND** 更新该短语的频率计数
- **AND** 更新该短语的最后出现时间

#### Scenario: 弹幕非中文/空内容过滤
- **WHEN** 弹幕内容为纯数字、纯标点、或长度 < 2 字符
- **THEN** 系统 SHALL 跳过该弹幕（不进入缓冲区）

### Requirement: 缓冲区容量管理
系统 SHALL 维护一个固定大小的环形缓冲区，避免内存无限增长。

#### Scenario: 缓冲区满时覆盖最旧数据
- **WHEN** 缓冲区达到 `max_size` 上限（默认 1000 条）
- **THEN** 系统 SHALL 丢弃最早的一条弹幕
- **AND** 更新频率统计表（减少被丢弃弹幕中各短语的计数）

### Requirement: 高频短语查询
系统 SHALL 提供按时间和频次过滤的高频短语查询接口，供采集管道消费。

#### Scenario: 获取最近高频短语
- **WHEN** 采集管道调用 `get_hot_phrases(min_freq=3, window_minutes=30)`
- **THEN** 系统 SHALL 返回在最近 30 分钟内出现 >= 3 次的短语列表
- **AND** 每条短语包含：文本(text)、频次(frequency)、首次出现时间(first_seen)、最后出现时间(last_seen)

#### Scenario: 缓冲区无数据
- **WHEN** 缓冲区为空或没有达到 min_freq 阈值的短语
- **THEN** 系统 SHALL 返回空列表
- **AND** 不阻塞采集管道

### Requirement: 缓冲区状态查询
系统 SHALL 提供缓冲区状态信息，用于监控和调试。

#### Scenario: 查询缓冲区统计
- **WHEN** 外部模块调用 `total_count` 或 `get_stats()`
- **THEN** 系统 SHALL 返回缓冲区当前弹幕总数、短语种类数、最早/最晚弹幕时间
