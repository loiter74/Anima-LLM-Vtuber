# Startup Script Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split monolithic `scripts/start.py` (642 lines) into a modular `scripts/start/` package.

**Architecture:** Extract into 5 modules (colors, process, services, web_config_server, browser) with a thin `start.py` entry point. No behavioral changes — pure refactoring.

**Tech Stack:** Python 3.13, no new dependencies.

**Design doc:** `docs/plans/archive/2026-05/2026-05-01-startup-refactor-design.md`

---

### Task 1: Create package directory + colors.py

**Files:**
- Create: `scripts/start/__init__.py` (placeholder)
- Create: `scripts/start/colors.py`

**Step 1: Create package directory**

```bash
mkdir -p scripts/start
```

**Step 2: Write colors.py**

Move lines 22-64 from `scripts/start.py` (Colors class + info/success/warn/error functions). Exact same code.

**Step 3: Verify import works**

Run: `python -c "from scripts.start.colors import info, success; info('test'); success('test')"`
Expected: No errors, colored output printed

**Step 4: Commit**

```bash
git add scripts/start/colors.py
git commit -m "refactor: extract colors.py from start.py"
```

---

### Task 2: Extract process.py

**Files:**
- Create: `scripts/start/process.py`

**Step 1: Write process.py**

Move `ProcessManager` class from `scripts/start.py:71-439`. Remove `start_frontend_dev()` method (dead Next.js code). Keep everything else identical.

**Step 2: Verify import works**

Run: `python -c "from scripts.start.process import ProcessManager; pm = ProcessManager(); print('OK')"`
Expected: No errors

**Step 3: Commit**

```bash
git add scripts/start/process.py
git commit -m "refactor: extract process.py (ProcessManager) from start.py"
```

---

### Task 3: Create web_config_server.py

**Files:**
- Create: `scripts/start/web_config_server.py`

**Step 1: Write web_config_server.py**

Extract the inline HTTP server from `start.py:287-311` into a proper file:

```python
"""Web configuration HTTP server for Anima."""
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class ConfigHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, web_dir="", **kwargs):
        super().__init__(*args, directory=web_dir, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.path = "/templates/config.html"
        super().do_GET()

    def log_message(self, *args):
        pass


def serve(web_dir: str, port: int = 8080):
    """Start the web config HTTP server."""
    server = HTTPServer(("0.0.0.0", port), lambda *a: ConfigHandler(*a, web_dir=web_dir))
    print(f"[Config] Web configuration interface started: http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve(sys.argv[1] if len(sys.argv) > 1 else ".", int(sys.argv[2]) if len(sys.argv) > 2 else 8080)
```

**Step 2: Test the server can start**

Run: `python -c "from scripts.start.web_config_server import serve; print('OK')"`
Expected: No errors

**Step 3: Commit**

```bash
git add scripts/start/web_config_server.py
git commit -m "refactor: extract web_config_server.py from inline string"
```

---

### Task 4: Create services.py

**Files:**
- Create: `scripts/start/services.py`

**Step 1: Write services.py**

Extract all service startup methods from `ProcessManager` into standalone functions:

```python
"""Service startup functions for Anima."""

import os
import subprocess
import sys
from pathlib import Path

from .colors import info, warn
from .process import ProcessManager


def start_backend(project_root: Path, pm: ProcessManager) -> tuple:
    """Start the Socket.IO backend server on port 12394."""
    info("Starting backend Socket.IO server (port 12394)...")
    python_exe = pm._get_venv_python(project_root)
    if python_exe != sys.executable:
        info(f"Using virtual environment: {python_exe}")
    src_path = project_root / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_path)
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [python_exe, "-m", "anima.core.socketio_server"],
        cwd=project_root, env=env, stdout=None, stderr=None,
    )
    return ("Backend", process, 12394)


def start_vite(project_root: Path) -> tuple:
    """Start the Vite frontend dev server on port 3000."""
    info("Starting Vite frontend (Vue 3 + Vite)...")
    frontend_dir = project_root / "frontend"
    node_modules = frontend_dir / "node_modules"
    needs_install = False
    if not node_modules.exists():
        warn("Frontend dependencies not installed, installing...")
        needs_install = True
    else:
        key_dept = frontend_dir / "node_modules" / "@vitejs" / "plugin-vue"
        if not key_dept.exists():
            info("Dependencies changed, updating...")
            needs_install = True
    if needs_install:
        subprocess.run(["pnpm", "install"], cwd=frontend_dir, shell=True, check=True)
    process = subprocess.Popen(
        ["pnpm", "run", "dev"], cwd=frontend_dir, shell=True, stdout=None, stderr=None,
    )
    return ("Frontend", process, None)


def start_web_config(project_root: Path, port: int = 8080) -> tuple:
    """Start the web configuration HTTP server."""
    info(f"Starting web configuration interface (port {port})...")
    python_exe = _get_venv_python(project_root)
    web_dir = project_root / "frontend" / "web"
    process = subprocess.Popen(
        [python_exe, "-m", "scripts.start.web_config_server", str(web_dir), str(port)],
        cwd=project_root, stdout=None, stderr=None,
    )
    return ("Web Config", process, port)


def start_vibe_voice(project_root: Path, pm: ProcessManager):
    """Start the VibeVoice TTS local inference server."""
    info("Starting VibeVoice TTS server (port 8765)...")
    python_exe = _get_venv_python(project_root)
    server_script = project_root / "scripts" / "vibe_voice_server.py"
    model_path = "E:/anima_data/models/VibeVoice/VibeVoice-1.5B"
    if not server_script.exists():
        warn(f"VibeVoice server script not found: {server_script}")
        return None
    if not os.path.isdir(model_path):
        warn(f"VibeVoice model directory not found: {model_path}")
        return None
    process = subprocess.Popen(
        [python_exe, str(server_script), "--port", "8765", "--model", model_path, "--device", "cuda"],
        cwd=project_root, stdout=None, stderr=None,
    )
    return ("VibeVoice TTS", process, 8765)


def _get_venv_python(project_root: Path) -> str:
    """Resolve venv Python path."""
    venv_paths = [
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
        project_root / "venv" / "Scripts" / "python.exe",
        project_root / "venv" / "bin" / "python",
    ]
    for p in venv_paths:
        if p.exists():
            return str(p)
    return sys.executable


def get_tts_provider(project_root: Path) -> str:
    """Read TTS provider from config.yaml."""
    try:
        import yaml
        cfg_path = project_root / "config" / "config.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        return (cfg or {}).get("services", {}).get("tts", "edge")
    except Exception:
        return "edge"
```

**Step 2: Verify import works**

Run: `python -c "from scripts.start.services import start_backend; print('OK')"`
Expected: No errors

**Step 3: Commit**

```bash
git add scripts/start/services.py
git commit -m "refactor: extract services.py from start.py"
```

---

### Task 5: Create browser.py

**Files:**
- Create: `scripts/start/browser.py`

**Step 1: Write browser.py**

```python
"""Auto-open browser for started services."""

import threading
import time
import webbrowser


def open_browser(urls: list[tuple[str, int]]):
    """
    Open multiple URLs in the browser with staggered delays.

    Args:
        urls: List of (url, delay_seconds) tuples.
    """
    def _open(url: str, delay: int):
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    for url, delay in urls:
        t = threading.Thread(target=_open, args=(url, delay), daemon=True)
        t.start()
```

**Step 2: Commit**

```bash
git add scripts/start/browser.py
git commit -m "refactor: extract browser.py from start.py"
```

---

### Task 6: Create __init__.py

**Files:**
- Create: `scripts/start/__init__.py`

**Step 1: Write __init__.py**

```python
from .colors import Colors, info, success, warn, error
from .process import ProcessManager
from .services import start_backend, start_vite, start_web_config, start_vibe_voice, get_tts_provider
from .browser import open_browser
```

**Step 2: Commit**

```bash
git add scripts/start/__init__.py
git commit -m "refactor: add start/ package __init__.py"
```

---

### Task 7: Rewrite start.py as thin entry point

**Files:**
- Modify: `scripts/start.py`

**Step 1: Rewrite start.py**

Replace the entire 642-line file with:

```python
#!/usr/bin/env python3
"""
Anima unified startup script.
Usage: python scripts/start.py [options]
"""

import argparse
import platform
import subprocess
import sys
import time
from pathlib import Path

from scripts.start import (
    Colors, info, success, warn, error,
    ProcessManager, open_browser,
    start_backend, start_vite, start_web_config, start_vibe_voice, get_tts_provider,
)


def main():
    parser = argparse.ArgumentParser(
        description="Anima unified startup script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/start.py                   # Default: backend + web config + desktop app
  python scripts/start.py --mode web        # Web mode: backend + Vite frontend
  python scripts/start.py --backend-only    # Backend only
        """,
    )
    parser.add_argument("--mode", choices=["desktop", "web"], default="desktop",
                        help="Run mode: desktop (Electron) or web (Vue 3 + Vite)")
    parser.add_argument("--backend-only", action="store_true", help="Start backend only")
    parser.add_argument("--no-backend", action="store_true", help="Skip backend")
    parser.add_argument("--no-web-config", action="store_true", help="Skip web config page")
    parser.add_argument("--no-app", action="store_true", help="Skip desktop/frontend app")
    parser.add_argument("--web-port", type=int, default=8080, help="Web config page port")
    parser.add_argument("--install", action="store_true", help="Reinstall dependencies")
    parser.add_argument("--dev", action="store_true", help="Enable DevTools")
    parser.add_argument("--no-tts-server", action="store_true", help="Skip TTS inference server")
    args = parser.parse_args()

    # Project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    os.chdir(project_root)

    # Print header
    print()
    header = "Anima Startup Script"
    print(f"{Colors.MAGENTA}{'=' * 50}{Colors.NC}" if Colors.enabled() else "=" * 50)
    print(f"{Colors.MAGENTA}  {header}{Colors.NC}" if Colors.enabled() else f"  {header}")
    print(f"{Colors.MAGENTA}{'=' * 50}{Colors.NC}" if Colors.enabled() else "=" * 50)
    print()

    # Check package manager
    pkg_manager = None
    use_shell = platform.system() == "Windows"
    for pm in ["pnpm", "npm"]:
        try:
            subprocess.run([pm, "--version"], capture_output=True, check=True, shell=use_shell)
            pkg_manager = pm
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    if pkg_manager:
        info(f"Package manager: {pkg_manager}")

    # Install dependencies if requested
    if args.install:
        info("Installing Python dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        if pkg_manager:
            info("Installing frontend dependencies...")
            subprocess.run([pkg_manager, "install"], check=True, cwd="frontend", shell=use_shell)
        print()

    # Stop existing services
    pm = ProcessManager()
    info("Checking and stopping existing services...")
    pm.stop_processes_on_port(12394, "Backend")
    pm.stop_processes_on_port(8765, "VibeVoice TTS")
    pm.stop_processes_on_port(8080, "Web Config")
    pm.stop_processes_on_port(3000, "Frontend")
    print()

    started = []  # (name, process, port)

    try:
        # TTS server
        if not args.no_tts_server and not args.backend_only:
            provider = get_tts_provider(project_root)
            if provider == "vibe_voice":
                info(f"TTS provider is {provider}, starting local inference server...")
                result = start_vibe_voice(project_root, pm)
                if result:
                    started.append(result)
                    time.sleep(3)
            else:
                info(f"TTS provider is {provider}, skipping VibeVoice")

        # Backend
        if not args.no_backend:
            started.append(start_backend(project_root, pm))
            time.sleep(2)

        # Web config
        if not args.no_web_config and not args.backend_only:
            started.append(start_web_config(project_root, args.web_port))
            time.sleep(1)

        # Frontend
        if not args.no_app and not args.backend_only:
            if not pkg_manager:
                error("Frontend requires pnpm/npm")
            started.append(start_vite(project_root))

        # Wait for services
        print()
        pm.wait_for_services()

        # Print status
        print()
        print(f"{Colors.GREEN}{'=' * 50}{Colors.NC}" if Colors.enabled() else "=" * 50)
        print(f"{Colors.GREEN}  All services started!{Colors.NC}" if Colors.enabled() else "  All services started!")
        print(f"{Colors.GREEN}{'=' * 50}{Colors.NC}" if Colors.enabled() else "=" * 50)
        print()

        urls = []
        if not args.no_backend:
            url = "http://localhost:12394"
            print(f"  Backend:     {Colors.CYAN}{url}{Colors.NC}" if Colors.enabled() else f"  Backend:     {url}")
            urls.append(("http://localhost:12394/health", 2))
        if not args.no_web_config and not args.backend_only:
            url = f"http://localhost:{args.web_port}"
            print(f"  Web Config:  {Colors.CYAN}{url}{Colors.NC}" if Colors.enabled() else f"  Web Config:  {url}")
            urls.append((url, 3))
        if not args.no_app and not args.backend_only:
            if args.mode == "desktop":
                print("  Desktop app: Electron window")
            else:
                url = "http://localhost:3000"
                print(f"  Frontend:    {Colors.CYAN}{url}{Colors.NC}" if Colors.enabled() else f"  Frontend:    {url}")
                urls.append((url, 3))

        print()
        info("Press Ctrl+C to stop all services\n")

        # Auto-open browser
        open_browser(urls)

        # Wait loop
        while True:
            all_stopped = True
            for _, process, _ in started:
                if process.poll() is None:
                    all_stopped = False
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
            if all_stopped:
                break

    except KeyboardInterrupt:
        pm.stop_all()


if __name__ == "__main__":
    main()
```

**Step 2: Test the entry point**

Run: `python scripts/start.py --help`
Expected: Help text displayed with all options

**Step 3: Run existing tests to verify nothing broke**

Run: `cd /c/Users/30262/Project/Anima && PYTHONPATH=src python -m pytest tests/ -q`
Expected: 81 passed

**Step 4: Commit**

```bash
git add scripts/start.py
git commit -m "refactor: rewrite start.py as thin entry point using start/ package"
```

---

### Task 8: Update README references

**Files:**
- Modify: `scripts/README.md` (if exists)

**Step 1: Check if scripts/README.md references need updating**

Check for stale references to the old monolithic script.

**Step 2: Commit if changes needed**

```bash
git add scripts/README.md
git commit -m "docs: update startup script documentation"
```
