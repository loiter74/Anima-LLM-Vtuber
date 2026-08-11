调用: pnpm -C frontend run live:sing-smoke -- --base-url http://127.0.0.1 --audio-file tests/fixtures/audio/singing_test.m4a --lyrics 测试 --duration-seconds 12
验收: task_id 一致; HTTP 200; playbackCount 递增; lastAudioKind=singing; state=playing|completed
边界: FFmpeg 兼容分离不代表 RVC 声线生效; 不启动任何服务
状态: 待生成
