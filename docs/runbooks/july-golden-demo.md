# July Golden Demo Runbook

目标是用 GPU Docker、真实 DeepSeek V4 Flash、Qwen3 Alice ICL 和单一 Live2D 模型完成可审计的十分钟本地闭环。

## 启动与门禁

```powershell
python scripts/runtime_lifecycle.py qwen-up
python scripts/runtime_lifecycle.py anima-down
python scripts/runtime_lifecycle.py anima-up
curl.exe -f http://localhost/health
curl.exe -f http://localhost/ready
docker compose logs --no-color > evidence/docker-golden.log
docker compose -f docker-compose.qwen.yml logs --no-color > evidence/qwen-golden.log
```

`/ready` 必须为 golden ready，并明确显示非 Mock 的 DeepSeek 与 `qwen3/alice_vc`。日志不得出现 Traceback、ERROR、Mock、provider substitution 或 orphan task。

## 自动证据

```powershell
$env:PYTHONPATH='src'
python scripts/validate-events.py
python scripts/smoke_qwen_alice.py
python scripts/qa_capture.py
python scripts/soak_golden_path.py --url http://localhost --duration 600 --turns 12 --log-file evidence/docker-golden.log
```

每次 QA 都创建新的时间戳目录和新的 task identity，不得复用旧截图。soak 报告写入 `evidence/golden-soak/`，失败也必须保留已收集证据。

## 三个演示

按 `config/demo/golden_scenarios.json` 顺序执行普通连续性、角色幽默/世界观、隔离的 TTS 降级恢复。故障演练不得与 clean soak 同时运行；演练后关闭故障注入并重新检查 `/ready`。

## 回滚

若任一门禁失败，停止发布并执行 `python scripts/runtime_lifecycle.py anima-down`。保留 evidence，不切换到 Mock，不修改 golden provider，也不要销毁仍健康的 Qwen。修复后从完整 Docker 协议重新开始；仅当 Qwen 镜像或模型契约确实变化时执行 `python scripts/runtime_lifecycle.py qwen-deploy`。
