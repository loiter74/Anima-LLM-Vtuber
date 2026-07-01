"""
Minecraft Bridge — Manages Mineflayer bot subprocess lifecycle and communication

Architecture:
  Anima startup → MinecraftBridge.start() → spawns Node.js subprocess
  LLM tool call → bridge.send_command(action, params) → JSON to stdin → wait response
  Bot idle → sends heartbeat events → Python tracks state
  Anima shutdown → MinecraftBridge.stop() → kill subprocess

Protocol:
  Request:  {"id": 1, "action": "goto", "params": {"x": 100, "y": 64, "z": 200}}
  Response: {"id": 1, "status": "success", "result": "Arrived at (100, 64, 200)"}
  Event:    {"id": null, "status": "event", "result": {"type": "heartbeat", ...}}
"""

import asyncio
import contextlib
import json
import os
from typing import TYPE_CHECKING, Any

from loguru import logger

from animetta.utils.service_availability import is_service_available

from .config import MinecraftConfig, MinecraftMode

if TYPE_CHECKING:
    pass  # ServicePool is accessed as a class, not imported for type checking


class MinecraftBridge:
    """Manages the Mineflayer bot subprocess with optional autonomous behavior"""

    def __init__(
        self,
        config: MinecraftConfig,
        autonomous: bool = False,
        service_pool: Any | None = None,
    ):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._running = False
        self._reader_task: asyncio.Task | None = None
        self._bot_ready = asyncio.Event()

        # Autonomous behavior loop (lazy init)
        self._autonomous_loop = None
        self._autonomous_enabled = autonomous
        self._service_pool = service_pool

        # Viewer callback for forwarding viewer_joined/viewer_left events
        self._viewer_callback: Any | None = None

        # Voyager 阶段（mc-bot-voyager-learning T9/T10）：learn/live/fallback
        self._voyager_mode: str | None = None
        self._learning_task: asyncio.Task | None = None
        self._skill_library: Any = None

    async def start(self) -> bool:
        """Start the Mineflayer bot subprocess"""
        if self._running:
            return True

        if not is_service_available("node"):
            logger.info("[MinecraftBridge] Skipped — Node.js not available in this environment")
            return False

        bot_dir = os.path.join(os.path.dirname(__file__), "..", "bot")
        bot_script = os.path.join(bot_dir, "index.js")

        if not os.path.exists(bot_script):
            logger.error(f"[MinecraftBridge] Bot script not found: {bot_script}")
            return False

        if not os.path.exists(os.path.join(bot_dir, "node_modules")):
            logger.error(
                f"[MinecraftBridge] node_modules not found, run 'npm install' in {bot_dir}"
            )
            return False

        try:
            # Build environment with viewer config
            env = os.environ.copy()
            if self.config.viewer.username:
                env["MC_VIEWER_USERNAME"] = self.config.viewer.username
                env["MC_AUTO_SPECTATE"] = "true" if self.config.viewer.auto_spectate else "false"
            if self.config.web_viewer.enabled:
                env["MC_WEB_VIEWER_ENABLED"] = "true"
                env["MC_WEB_VIEWER_HOST"] = self.config.web_viewer.host
                env["MC_WEB_VIEWER_PORT"] = str(self.config.web_viewer.port)

            # Export client-viewer (real Minecraft client capture) settings
            cv = self.config.client_viewer
            if cv.enabled:
                env["MC_CLIENT_VIEWER_ENABLED"] = "true"
                env["MC_CLIENT_VIEWER_USERNAME"] = cv.username
                env["MC_CLIENT_VIEWER_MODE"] = cv.mode
                env["MC_CLIENT_VIEWER_AUTO_SPECTATE"] = "true" if cv.auto_spectate else "false"
                env["MC_CLIENT_VIEWER_POLL_INTERVAL"] = str(cv.poll_interval)
                env["MC_CLIENT_VIEWER_SPECTATE_TIMEOUT"] = str(cv.spectate_timeout)

            self._process = await asyncio.create_subprocess_exec(
                "node",
                bot_script,
                self.config.bot.host,
                str(self.config.bot.port),
                self.config.bot.username,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=bot_dir,
                env=env,
            )

            self._running = True

            # Start reader tasks
            self._reader_task = asyncio.create_task(self._read_stdout())
            asyncio.create_task(self._read_stderr())

            logger.info(
                f"[MinecraftBridge] Bot process started (PID: {self._process.pid}, "
                f"server={self.config.bot.host}:{self.config.bot.port})"
            )

            # Wait for bot to log in
            try:
                await asyncio.wait_for(self._bot_ready.wait(), timeout=15.0)
                logger.info("[MinecraftBridge] Bot logged in successfully")
            except TimeoutError:
                logger.warning("[MinecraftBridge] Bot login timeout, continuing anyway")

            # Start autonomous loop if enabled
            if self._autonomous_enabled:
                await self._start_autonomous()

            return True

        except Exception as e:
            logger.error(f"[MinecraftBridge] Failed to start: {e}")
            return False

    async def send_command(
        self, action: str, params: dict | None = None, timeout: float = 60.0
    ) -> dict:
        """Send a command to the bot and wait for response

        Args:
            action: Bot action name (goto, mine, place, attack, chat, status, etc.)
            params: Action parameters
            timeout: Max wait time in seconds (default 60)

        Returns:
            Dict with status and result keys
        """
        if not self._running or not self._process:
            return {"status": "error", "result": "Bridge not running"}

        if self._process.returncode is not None:
            self._running = False
            return {"status": "error", "result": "Bot process has exited"}

        async with self._lock:
            cmd_id = self._next_id
            self._next_id += 1
            future = asyncio.get_event_loop().create_future()
            self._pending[cmd_id] = future

        command = json.dumps(
            {
                "id": cmd_id,
                "action": action,
                "params": {**(params or {}), "timeout": int(timeout * 1000)},
            }
        )
        logger.debug(f"[MinecraftBridge] Sending: {action} (id={cmd_id})")

        try:
            self._process.stdin.write((command + "\n").encode("utf-8"))
            await self._process.stdin.drain()

            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except TimeoutError:
            logger.warning(f"[MinecraftBridge] Command '{action}' timeout after {timeout}s")
            return {"status": "error", "result": f"Command timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"[MinecraftBridge] Command '{action}' failed: {e}")
            return {"status": "error", "result": str(e)}
        finally:
            self._pending.pop(cmd_id, None)

    async def _read_stdout(self):
        """Read JSON responses from bot stdout"""
        try:
            _connection_refused_logged = False
            while self._running and self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    logger.info("[MinecraftBridge] Bot stdout closed")
                    break

                line = line.decode("utf-8").strip()
                if not line:
                    continue

                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    # Suppress noisy individual line warnings when connection is refused
                    if "ECONNREFUSED" in line:
                        if not _connection_refused_logged:
                            logger.info(
                                "[MinecraftBridge] Minecraft server not available on localhost:25565"
                            )
                            _connection_refused_logged = True
                    else:
                        logger.debug(f"[MinecraftBridge] Non-JSON from bot: {line[:100]}")
                    continue

                resp_id = response.get("id")
                status = response.get("status")
                result = response.get("result")

                if resp_id == "system" or (resp_id is None and status == "event"):
                    # Handle events
                    if isinstance(result, dict) and result.get("type") == "heartbeat":
                        logger.debug(f"[MinecraftBridge] Heartbeat: {result}")
                    elif isinstance(result, dict) and result.get("type") == "login":
                        logger.info(f"[MinecraftBridge] Bot logged in: {result.get('username')}")
                        self._bot_ready.set()
                    elif isinstance(result, dict) and result.get("type") == "spawn":
                        logger.info("[MinecraftBridge] Bot spawned in world")
                    elif isinstance(result, dict) and result.get("type") in (
                        "viewer_joined",
                        "viewer_left",
                    ):
                        event_type = result["type"]
                        event_username = result.get("username", "")
                        logger.info(f"[MinecraftBridge] {event_type}: {event_username}")
                        if self._viewer_callback:
                            try:
                                self._viewer_callback(event_type, event_username)
                            except Exception as e:
                                logger.error(f"[MinecraftBridge] Viewer callback error: {e}")
                    elif isinstance(result, dict) and result.get("type") == "client_viewer_status":
                        logger.info(
                            "[MinecraftBridge] client_viewer_status: "
                            f"{result.get('state', '')} {result.get('username', '')}"
                        )
                        if self._viewer_callback:
                            try:
                                self._viewer_callback("client_viewer_status", result)
                            except Exception as e:
                                logger.error(f"[MinecraftBridge] Viewer callback error: {e}")
                    continue

                if resp_id is not None and resp_id in self._pending:
                    self._pending[resp_id].set_result({"status": status, "result": result})
                else:
                    logger.debug(f"[MinecraftBridge] Unhandled response id={resp_id}")

        except asyncio.CancelledError:
            logger.debug("[MinecraftBridge] stdout reader cancelled")
        except Exception as e:
            logger.error(f"[MinecraftBridge] stdout reader error: {e}")
        finally:
            self._running = False

    async def _read_stderr(self):
        """Log bot stderr output"""
        try:
            while self._process and self._process.stderr:
                line = await self._process.stderr.readline()
                if not line:
                    break
                msg = line.decode("utf-8").strip()
                if msg:
                    logger.debug(f"[MinecraftBot] {msg}")
        except Exception as e:
            logger.debug(f"[MinecraftBridge] stderr reader stopped: {e}")

    async def _start_autonomous(self):
        """Start autonomous behavior — Voyager learn loop (LEARN) or rules loop (LIVE/fallback)."""
        from ..autonomous.loop import AutonomousLoop
        from ..other.trace_recorder import TraceRecorder
        from ..skill.library import SkillLibrary
        from ..skill.validator import SkillValidator

        llm_service = None
        if self._service_pool is not None:
            try:
                llm_service = getattr(self._service_pool, "_llm", None)
            except Exception:
                logger.warning("[MinecraftBridge] Could not get LLM service from ServicePool")

        # 解析 Voyager 模式：set_voyager_mode 优先，回落 config.mode（T9）
        cfg_mode = getattr(self.config, "mode", None)
        if self._voyager_mode is not None:
            mode = self._voyager_mode
        elif cfg_mode == MinecraftMode.LEARN:
            mode = "learn"
        elif cfg_mode == MinecraftMode.LIVE:
            mode = "live"
        else:
            mode = "fallback"
        self._voyager_mode = mode

        # 共享 skill library（学习期/直播期都用）；无 LLM 则不建库
        if llm_service is not None:
            library = SkillLibrary(db_path="data/mc_skills.db")
            await library.init_db()
            await library.load_predefined_skills()
            self._skill_library = library
        else:
            library = None

        # LEARN + LLM → Voyager 学习闭环后台跑（替代规则循环，T9）
        if mode == "learn" and llm_service is not None and library is not None:
            await self._launch_learning_loop(library, llm_service)
            return

        # LIVE / fallback / 无 LLM → 规则 AutonomousLoop（LIVE 期具体 goal 由 LiveAgent 驱动）
        if llm_service is not None and library is not None:
            from ..skill.extractor import SkillExtractor

            extractor = SkillExtractor(llm_service=llm_service, skill_library=library)
            validator = SkillValidator()
            recorder = TraceRecorder(output_dir="data/mc_traces")
            self._autonomous_loop = AutonomousLoop(
                self,
                skill_library=library,
                skill_extractor=extractor,
                skill_validator=validator,
                trace_recorder=recorder,
            )
            logger.info("[MinecraftBridge] Autonomous loop started WITH learning components")
        else:
            # Graceful degradation: pure rule-based loop
            if self._service_pool is not None:
                logger.warning(
                    "[MinecraftBridge] ServicePool available but no LLM service — "
                    "running without learning"
                )
            self._autonomous_loop = AutonomousLoop(self)
            logger.info("[MinecraftBridge] Autonomous loop started (no learning — rule-based only)")

        await self._autonomous_loop.start()

    async def _launch_learning_loop(self, library, llm_service) -> None:
        """T9: 后台启动 Voyager 学习闭环（run_learning_loop），不阻塞 bridge.start。

        复用 ``other.self_evolution.run_learning_loop``（经 mc-evo-purity 测试覆盖的核心）。
        bridge 生命周期由调用方管理；本方法只创建后台 task。
        """
        from ..other.self_evolution import run_learning_loop

        # 加载 code seeds 作 reference（学习期检索复用 verified 技能）
        try:
            from ..skill.code_seeds import get_code_seeds

            for seed in get_code_seeds():
                await library.save_skill(seed)
        except Exception as e:
            logger.warning(f"[MinecraftBridge] load code seeds failed: {e}")

        self._learning_task = asyncio.create_task(run_learning_loop(self, library, llm_service))
        logger.info("[MinecraftBridge] Voyager LEARN loop started in background")

    async def _stop_autonomous(self):
        """Stop the autonomous behavior loop / learning loop"""
        if self._learning_task is not None:
            self._learning_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._learning_task
            self._learning_task = None
        if self._autonomous_loop:
            await self._autonomous_loop.stop()
            self._autonomous_loop = None

    def pause_autonomous(self):
        """Pause autonomous decisions (e.g., LLM instruction active)"""
        if self._autonomous_loop:
            self._autonomous_loop.pause()

    def resume_autonomous(self):
        """Resume autonomous decisions after LLM instruction"""
        if self._autonomous_loop:
            self._autonomous_loop.resume()

    # ── Voyager 阶段切换（mc-bot-voyager-learning T10/T13）──

    async def set_voyager_mode(self, mode: str) -> dict:
        """切换 Voyager 阶段：learn / live / fallback。

        记录期望模式；若 bridge 已运行，按需启停学习闭环（切到 LEARN 且未在学 → 后台
        拉起 ``run_learning_loop``；切离 LEARN → 取消学习 task）。规则 AutonomousLoop
        （若有）同步模式。实际 learn 闭环的运行验证见 T9/T15（需实机）。
        """
        self._voyager_mode = mode
        if self._autonomous_loop is not None:
            self._autonomous_loop.set_voyager_mode(mode)

        if mode == "learn" and self._running and self._learning_task is None:
            # bridge 已启动后切到 learn → 后台拉起学习闭环
            llm = getattr(self._service_pool, "_llm", None) if self._service_pool else None
            if llm is not None and self._skill_library is not None:
                await self._launch_learning_loop(self._skill_library, llm)
            else:
                logger.warning("[MinecraftBridge] 无法启动 learn loop：缺 LLM 或 skill library")
        elif mode != "learn" and self._learning_task is not None:
            self._learning_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._learning_task
            self._learning_task = None
            logger.info("[MinecraftBridge] Voyager LEARN loop stopped (mode switched)")

        logger.info(f"[MinecraftBridge] voyager mode = {mode}")
        return {"status": "ok", "voyager_mode": mode}

    # ── Mode Commands (for planner integration) ──

    async def set_planner_mode(self, plan_steps: list) -> dict:
        """Switch bot to planner mode with a plan"""
        return await self.send_command(
            "set_mode",
            {
                "mode": "planner",
                "plan": plan_steps,
            },
            timeout=10.0,
        )

    async def set_rule_mode(self) -> dict:
        """Switch bot to rule mode (Python-driven)"""
        return await self.send_command(
            "set_mode",
            {
                "mode": "rule",
            },
            timeout=10.0,
        )

    async def get_plan_status(self) -> dict:
        """Get current plan execution status"""
        return await self.send_command("plan_status", {}, timeout=5.0)

    async def spectate_viewer(self, username: str | None = None) -> dict:
        """Send spectate command to attach viewer to bot's perspective.

        Args:
            username: Viewer's MC username. If None, uses config.viewer.username.

        Returns:
            Dict with status and result keys.
        """
        params = {}
        if username:
            params["username"] = username
        return await self.send_command("spectate", params, timeout=10.0)

    def set_viewer_callback(self, callback: Any) -> None:
        """Set callback for viewer join/leave events.

        The callback receives: (event_type: str, username: str)
        where event_type is 'viewer_joined' or 'viewer_left'.
        """
        self._viewer_callback = callback

    async def stop(self):
        """Stop the bot subprocess and autonomous loop"""
        self._running = False

        # Stop autonomous loop first
        await self._stop_autonomous()

        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
                logger.info("[MinecraftBridge] Bot process terminated")
            except TimeoutError:
                try:
                    self._process.kill()
                    await self._process.wait()
                    logger.warning("[MinecraftBridge] Bot process killed (timeout)")
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass

        # Resolve all pending futures with error
        for future in self._pending.values():
            if not future.done():
                future.set_result({"status": "error", "result": "Bridge stopped"})
        self._pending.clear()

        logger.info("[MinecraftBridge] Bridge stopped")

    @property
    def is_running(self) -> bool:
        return self._running


# Module-level singleton
_bridge: MinecraftBridge | None = None


def get_bridge() -> MinecraftBridge | None:
    """Get the global bridge instance"""
    return _bridge
