## 1. 事件常量定义

- [x] 1.1 创建 `config/socket-events.json`，定义所有 48 个事件（点分隔格式 + payload 类型）
- [x] 1.2 创建 `frontend/src/constants/socket-events.ts`，从 JSON 生成 TypeScript 类型
- [x] 1.3 创建 `scripts/validate-events.py`，验证 JSON 与代码中的事件名一致

## 2. 后端迁移

- [x] 2.1 修改 `routes.py`，从 JSON 读取事件名
- [x] 2.2 迁移 `output_node.py` 中的 emit（sentence, control, expression, live2d.action, audio_with_expression）
- [x] 2.3 迁移 `asr_node.py` 中的 emit（transcript）
- [x] 2.4 迁移 `lifecycle_handlers.py` 中的 emit（connection-established, control）
- [x] 2.5 迁移 `chat_handlers.py` 中的 emit（stop_audio, control）
- [x] 2.6 迁移 `singing_handlers.py` 中的 emit（sing:progress, sing:complete, sing:error, sing:lyrics_ready, sing:subtitle_line）
- [x] 2.7 迁移 `bilibili_handlers.py` 中的 emit（danmaku, danmaku.status, danmaku.ai_reply）
- [x] 2.8 迁移 `minecraft_handlers.py` 中的 emit（minecraft.status）
- [x] 2.9 迁移 `config_handlers.py` 中的 emit（config-switched, log_level_changed, config_data, heartbeat-ack, translation.status）
- [x] 2.10 迁移 `model_loading_manager.py` 中的 emit（model_status）

## 3. 前端迁移

- [x] 3.1 在 `useChat.ts` 中导入并使用事件常量替换所有字符串字面量
- [x] 3.2 在 `useVoice.ts` 中导入并使用事件常量
- [x] 3.3 在 `useDanmaku.ts` 中导入并使用事件常量
- [x] 3.4 在 `useSinging.ts` 中导入并使用事件常量
- [x] 3.5 在 `useSubtitle.ts` 中导入并使用事件常量
- [x] 3.6 在 `useSocket.ts` 中导入并使用事件常量
- [x] 3.7 在 `useLive2D.ts` 中导入并使用事件常量
- [x] 3.8 在 `stores/minecraft.ts` 中导入并使用事件常量
- [x] 3.9 在 `stores/personality.ts` 中导入并使用事件常量
- [x] 3.10 在 `stores/memory.ts` 中导入并使用事件常量
- [x] 3.11 在 `stores/memeReview.ts` 中导入并使用事件常量
- [x] 3.12 在 `components/settings/SettingsPanel.vue` 中导入并使用事件常量
- [x] 3.13 在 `components/memory/MemoryPanel.vue` 中导入并使用事件常量
- [x] 3.14 在 `views/MemeReview.vue` 中导入并使用事件常量
- [x] 3.15 在 `views/MusicPage.vue` 中导入并使用事件常量

## 4. 测试验证

- [ ] 4.1 运行验证脚本，确保 JSON 与代码中的事件名一致
- [ ] 4.2 启动后端，验证所有事件注册成功，无报错
- [ ] 4.3 启动前端，验证所有事件监听注册成功
- [ ] 4.4 测试对话流程：发送文本→接收回复→播放音频
- [ ] 4.5 测试语音流程：录音→识别→回复
- [ ] 4.6 测试唱歌流程：选择歌曲→处理→播放
- [ ] 4.7 测试人格切换：获取列表→切换人格
- [ ] 4.8 测试记忆功能：获取页面→整理记忆

## 5. CI/CD 集成

- [x] 5.1 修改 `Dockerfile`，添加验证步骤
- [ ] 5.2 验证 Docker 构建失败时阻止部署

## 6. 文档更新

- [x] 6.1 更新 `BACKEND_API_DOCUMENTATION.md`，添加新旧事件名对照表
- [ ] 6.2 更新 `API_DOCUMENTATION.md`，标注所有旧事件名为 deprecated
- [ ] 6.3 在 README.md 中添加事件命名规范说明
