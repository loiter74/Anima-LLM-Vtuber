# bilibili-meme-collector Specification

## Purpose
从 B 站定期采集热门视频和评论，识别新兴梗并提取关键上下文，为 MemePool 提供外部数据源。
## Requirements
### Requirement: 热门视频采集
系统 SHALL 定期从 B 站热门分区采集视频信息，包括标题、标签（tags）、播放量、视频描述。

#### Scenario: 每日定时采集
- **WHEN** PeriodicLearner 触发 `collect_bilibili_memes()` 调度任务
- **THEN** 系统使用 `bilibili-api-python` 的搜索接口获取热门视频列表
- **AND** 每个视频提取标题（title）、标签（tags）、播放量（view_count）、简介（description）
- **AND** 每次采集不超过 50 个视频

#### Scenario: API 请求限流保护
- **WHEN** 发起 B 站 API 请求
- **THEN** 系统 SHALL 在请求间插入至少 0.3 秒延迟
- **AND** 单次采集不超过 50 个视频
- **AND** 并行请求数不超过 5 个（使用 semaphore 控制）

#### Scenario: API 调用失败降级
- **WHEN** B 站 API 返回错误或超时
- **THEN** 系统 SHALL 记录 warning 日志
- **AND** 返回已成功采集的部分数据（而非整体失败）

#### Scenario: 采集超时保护
- **WHEN** 整体采集超过 120 秒
- **THEN** 系统 SHALL 触发 `asyncio.wait_for` 超时
- **AND** 返回当前已采集的数据（而非空列表）

### Requirement: 高赞评论抓取
系统 SHALL 对采集到的热门视频抓取其高赞评论（按点赞数排序前 50 条），使用并行方式提升效率。

#### Scenario: 评论抓取
- **WHEN** 获取到热门视频列表
- **THEN** 系统 SHALL 使用 `asyncio.gather` 并行抓取最多 50 个视频的评论
- **AND** 每个视频抓取前 50 条高赞评论
- **AND** 并行数受 semaphore（默认 5）控制
- **AND** 每条评论包含：内容、点赞数、回复数、发布时间

#### Scenario: 评论点赞门槛
- **WHEN** 筛选评论
- **THEN** 系统 SHALL 只保留点赞数 >= 2 的评论
- **AND** 跳过空内容评论

#### Scenario: 评论为空的视频
- **WHEN** 视频无评论或评论 API 返回空
- **THEN** 系统 SHALL 跳过该视频的评论分析
- **AND** 仍保留视频标题和标签用于梗识别

### Requirement: 梗候选识别
系统 SHALL 从采集到的视频标题、评论及弹幕数据中识别潜在的梗候选。

#### Scenario: 多源梗候选识别
- **WHEN** 完成视频、评论和弹幕采集
- **THEN** 系统 SHALL 使用 LLM 分析标题、高频评论和弹幕高频短语
- **AND** 识别重复出现的特定短语、句式或概念
- **AND** 标记"在弹幕中高频出现"的候选
- **AND** 标记"跨多个视频出现"的候选（交叉验证）
- **AND** 每个候选附带出现频次和来源

#### Scenario: 无新梗可识别
- **WHEN** LLM 分析后未发现新兴梗模式
- **THEN** 系统 SHALL 返回空列表
- **AND** 记录 info 日志 "No new meme candidates found"

### Requirement: 弹幕数据采集
系统 SHALL 新增弹幕数据源，从实时弹幕缓冲区 (`DanmakuBuffer`) 和历史弹幕 API (`live.get_danmaku`) 获取弹幕文本。

#### Scenario: 实时弹幕采集
- **WHEN** `DanmakuBuffer` 不为空且包含高频短语
- **THEN** 系统 SHALL 读取 `get_hot_phrases(min_freq=3, window_minutes=30)` 的结果
- **AND** 将高频短语加入 LLM 分析的上下文

#### Scenario: 历史弹幕采集
- **WHEN** 系统中配置了 B 站直播间 room_id
- **THEN** 系统 SHALL 调用 `live.get_danmaku(room_id)` 获取历史弹幕
- **AND** 提取弹幕中出现的高频短语
- **AND** 将弹幕文本加入 LLM 分析的上下文

#### Scenario: 弹幕源不可用
- **WHEN** 无直播间配置 或 `DanmakuBuffer` 为空 或历史弹幕 API 失败
- **THEN** 系统 SHALL 跳过弹幕采集
- **AND** 仅使用视频和评论数据进行梗识别
- **AND** 记录 info 日志

### Requirement: Heuristic 语义级短语提取
系统 SHALL 在 LLM 不可用时使用 jieba 分词 + 语义 n-gram 进行降级识别。

#### Scenario: Heuristic 降级识别
- **WHEN** LLM 客户端不可用或 LLM 调用失败
- **THEN** 系统 SHALL 使用 jieba 分词对视频标题、评论和弹幕进行分词
- **AND** 提取 2-4 个词的语义 n-gram
- **AND** 使用 TF-IDF 过滤通用高频词
- **AND** 按跨文档频次排序取 top 20

#### Scenario: jieba 导入失败
- **WHEN** jieba 库未安装
- **THEN** 系统 SHALL 回退到原有的字符 2-gram 方法
- **AND** 记录 warning 日志提示安装 jieba
