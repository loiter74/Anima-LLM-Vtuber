#!/usr/bin/env python3
"""
Anima Project Startup Script (Cross-platform)
Usage: python scripts/start.py [options]
"""

import os
import sys
import time
import platform
import subprocess
import argparse
from pathlib import Path


# ===========================
# Colors and Output
# ===========================

class Colors:
    """ANSI color codes"""
    CYAN = '\033[0;36m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    RED = '\033[0;31m'
    MAGENTA = '\033[0;35m'
    GRAY = '\033[0;90m'
    NC = '\033[0m'  # No Color

    @staticmethod
    def enabled():
        """Check if colors are supported"""
        return platform.system() != "Windows" or os.getenv('TERM')


def info(msg):
    print(f"{Colors.CYAN}[INFO]{Colors.NC} {msg}" if Colors.enabled() else f"[INFO] {msg}")

def success(msg):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}" if Colors.enabled() else f"[SUCCESS] {msg}")

def warn(msg):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}" if Colors.enabled() else f"[WARNING] {msg}")

def error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}" if Colors.enabled() else f"[ERROR] {msg}")
    sys.exit(1)


# ===========================
# Process Management
# ===========================

class ProcessManager:
    """Cross-platform process management"""

    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        self.backend_pid = None
        self.frontend_pid = None

    def find_processes_on_port(self, port):
        """Find process IDs listening on a port"""
        pids = []

        if self.is_windows:
            # Windows: use netstat
            try:
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = int(parts[-1])
                            if pid not in pids:
                                pids.append(pid)
            except subprocess.CalledProcessError:
                pass
        else:
            # Unix: use lsof
            try:
                result = subprocess.run(
                    ['lsof', '-ti', f':{port}'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                pids = [int(pid.strip()) for pid in result.stdout.split('\n') if pid.strip()]
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

        return pids

    def stop_process(self, pid, service_name):
        """Stop a process by PID"""
        if not pid:
            return True

        try:
            if self.is_windows:
                subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=True)
            else:
                subprocess.run(['kill', '-9', str(pid)], check=True)
            success(f"{service_name} process stopped (PID: {pid})")
            return True
        except subprocess.CalledProcessError as e:
            warn(f"Could not stop process {pid}: {e}")
            return False

    def stop_processes_on_port(self, port, service_name):
        """Stop all processes listening on a port"""
        info(f"Checking for existing {service_name} on port {port}...")

        pids = self.find_processes_on_port(port)

        if not pids:
            success(f"Port {port} is free")
            return True

        pid_list = ', '.join(map(str, pids))
        warn(f"Found process(es) on port {port}: PID {pid_list}")

        for pid in pids:
            self.stop_process(pid, service_name)
            time.sleep(0.5)

        # Verify
        time.sleep(1)
        remaining = self.find_processes_on_port(port)
        if remaining:
            error(f"Port {port} is still in use")
            return False

        success(f"Port {port} released")
        return True

    def start_backend(self, project_root, skip_backend):
        """Start the backend server"""
        if skip_backend:
            return None

        info("Starting backend server (port 12394)...")

        # Set environment
        src_path = project_root / "src"
        env = os.environ.copy()
        env['PYTHONPATH'] = str(src_path)

        # Command
        cmd = [sys.executable, '-m', 'anima.socketio_server']

        try:
            if self.is_windows:
                # Windows: start in background (without new window for debugging)
                # Use CREATE_NEW_PROCESS_GROUP to avoid being killed when script ends
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                process = subprocess.Popen(
                    cmd,
                    cwd=project_root,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags
                )
                self.backend_pid = process.pid
            else:
                # Unix: start in background
                process = subprocess.Popen(
                    cmd,
                    cwd=project_root,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.backend_pid = process.pid

            success("Backend started")

            # Wait for backend to start
            info("Waiting for backend to start...")
            for _ in range(15):
                time.sleep(2)
                if self.find_processes_on_port(12394):
                    success("Backend is listening on port 12394")
                    return

            error("Backend failed to start")

        except Exception as e:
            error(f"Failed to start backend: {e}")

    def start_frontend(self, project_root, pkg_manager, skip_frontend):
        """Start the frontend dev server"""
        if skip_frontend:
            return None

        info("Starting frontend dev server...")

        # Set environment
        env = os.environ.copy()
        env['NEXT_PRIVATE_BENCHMARK_ENABLED'] = 'false'
        env['NODE_OPTIONS'] = '--no-warnings'

        # Command
        frontend_dir = project_root / "frontend"
        cmd = [pkg_manager, 'dev']

        try:
            if self.is_windows:
                # Windows: start in background
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                process = subprocess.Popen(
                    cmd,
                    cwd=frontend_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags
                )
                self.frontend_pid = process.pid
            else:
                # Unix: start in background
                process = subprocess.Popen(
                    cmd,
                    cwd=frontend_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.frontend_pid = process.pid

            success("Frontend started")

            # Wait for frontend to start
            info("Waiting for frontend to start...")
            for _ in range(25):
                time.sleep(2)
                if self.find_processes_on_port(3000):
                    success("Frontend is listening on port 3000")
                    return

            warn("Frontend not yet listening on port 3000 (may still be compiling...)")

        except Exception as e:
            error(f"Failed to start frontend: {e}")


# ===========================
# Main
# ===========================

def main():
    parser = argparse.ArgumentParser(
        description='Anima Project Startup Script',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/start.py              # Start all services
  python scripts/start.py --skip-backend  # Start only frontend
  python scripts/start.py --install    # Reinstall dependencies
        """
    )

    parser.add_argument('--skip-backend', action='store_true', help='Skip backend startup')
    parser.add_argument('--skip-frontend', action='store_true', help='Skip frontend startup')
    parser.add_argument('--install', action='store_true', help='Reinstall dependencies')
    parser.add_argument('--auto-config', action='store_true', help='Auto-configure environment')

    args = parser.parse_args()

    # Print header
    print()
    if Colors.enabled():
        print(f"{Colors.MAGENTA}{'=' * 40}{Colors.NC}")
        print(f"{Colors.MAGENTA}  Anima Project Startup Script{Colors.NC}")
        print(f"{Colors.MAGENTA}{'=' * 40}{Colors.NC}")
    else:
        print('=' * 40)
        print('  Anima Project Startup Script')
        print('=' * 40)
    print()

    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    os.chdir(project_root)

    # Check Python
    if not os.path.exists(sys.executable):
        error("Python not found")

    # Check package manager
    pkg_manager = None
    use_shell = platform.system() == "Windows"
    for pm in ['pnpm', 'npm']:
        try:
            subprocess.run([pm, '--version'], capture_output=True, check=True, shell=use_shell)
            pkg_manager = pm
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if not pkg_manager:
        error("Node.js not found (pnpm/npm not found)")

    if pkg_manager == 'npm':
        warn("pnpm not found, using npm")

    info(f"Package manager: {pkg_manager}")
    info(f"Python: {sys.executable}")
    print()

    # Process manager
    pm = ProcessManager()

    # Phase 1: Stop existing services
    if Colors.enabled():
        print(f"{Colors.YELLOW}{'=' * 40}{Colors.NC}")
        print(f"{Colors.YELLOW}  Phase 1: Stopping Existing Services{Colors.NC}")
        print(f"{Colors.YELLOW}{'=' * 40}{Colors.NC}")
    else:
        print('=' * 40)
        print('  Phase 1: Stopping Existing Services')
        print('=' * 40)
    print()

    if not args.skip_backend:
        pm.stop_processes_on_port(12394, "Backend")

    if not args.skip_frontend:
        pm.stop_processes_on_port(3000, "Frontend")

    success("All existing services stopped")
    print()

    # Phase 2: Install dependencies
    if args.install:
        if Colors.enabled():
            print(f"{Colors.YELLOW}{'=' * 40}{Colors.NC}")
            print(f"{Colors.YELLOW}  Phase 2: Installing Dependencies{Colors.NC}")
            print(f"{Colors.YELLOW}{'=' * 40}{Colors.NC}")
        else:
            print('=' * 40)
            print('  Phase 2: Installing Dependencies')
            print('=' * 40)
        print()

        info("Installing backend dependencies...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)

        info("Installing frontend dependencies...")
        subprocess.run([pkg_manager, 'install'], check=True, cwd='frontend')
        print()

    # Phase 3: Start services
    if Colors.enabled():
        print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
        print(f"{Colors.GREEN}  Phase 3: Starting Services{Colors.NC}")
        print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
    else:
        print('=' * 40)
        print('  Phase 3: Starting Services')
        print('=' * 40)
    print()

    pm.start_backend(project_root, args.skip_backend)
    pm.start_frontend(project_root, pkg_manager, args.skip_frontend)

    # Done
    print()
    if Colors.enabled():
        print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
        print(f"{Colors.GREEN}  Startup Complete!{Colors.NC}")
        print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
    else:
        print('=' * 40)
        print('  Startup Complete!')
        print('=' * 40)
    print()

    if not args.skip_backend:
        if Colors.enabled():
            print(f"  Backend:  {Colors.CYAN}http://localhost:12394{Colors.NC}")
        else:
            print("  Backend:  http://localhost:12394")

    if not args.skip_frontend:
        if Colors.enabled():
            print(f"  Frontend: {Colors.CYAN}http://localhost:3000{Colors.NC}")
        else:
            print("  Frontend: http://localhost:3000")

    print()
    info("Services are running in separate windows.")
    print()
    warn("To stop services:")
    print("  - Windows: Press Ctrl+C in each window, or run: python scripts/stop.py")
    print("  - Unix: Press Ctrl+C in each terminal, or run: python scripts/stop.py")
    print()


if __name__ == "__main__":
    main()
